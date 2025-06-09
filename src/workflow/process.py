import logging
import uuid
import asyncio
from typing import Optional, Dict, Any, AsyncGenerator
from src.workflow import build_graph, agent_factory_graph
from src.manager import agent_manager
from src.interface.agent_types import TaskType
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from src.interface.agent_types import State
from src.service.env import USE_BROWSER

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

console = Console()

def enable_debug_logging():
    """Enable debug level logging for more detailed execution information."""
    logging.getLogger("src").setLevel(logging.DEBUG)


logger = logging.getLogger(__name__)

# 如果环境变量USE_BROWSER为True，那么默认的智能体描述中包含browser智能体
if USE_BROWSER:
    DEFAULT_TEAM_MEMBERS_DESCRIPTION = """
        - **`researcher`**: 使用搜索引擎和网络爬虫从互联网收集信息。输出一个Markdown报告总结发现。研究员不能进行数学或编程。
        - **`coder`**: 执行Python或Bash命令，执行数学计算，并输出一个Markdown报告。必须用于所有数学计算。
        - **`browser`**: 直接与网页交互，执行复杂操作和交互。你也可以利用`browser`执行域内搜索，比如Facebook，Instagram，Github等。
        - **`reporter`**: 根据每个步骤的结果写一个专业报告。
        - **`agent_factory`**: 根据用户的需求创建一个新智能体。
        """
else:
    DEFAULT_TEAM_MEMBERS_DESCRIPTION = """
        - **`researcher`**: 使用搜索引擎和网络爬虫从互联网收集信息。输出一个Markdown报告总结发现。研究员不能进行数学或编程。
        - **`coder`**: 执行Python或Bash命令，执行数学计算，并输出一个Markdown报告。必须用于所有数学计算。
        - **`reporter`**: 根据每个步骤的结果写一个专业报告。
        - **`agent_factory`**: 根据用户的需求创建一个新智能体。
        """

# Cache for coordinator messages
coordinator_cache = []
MAX_CACHE_SIZE = 2


async def run_agent_workflow(
    user_id: str,
    task_type: str,
    user_input_messages: list,
    debug: bool = False,
    deep_thinking_mode: bool = False,
    search_before_planning: bool = False,
    coor_agents: Optional[list[str]] = None,
):
    """根据用户的输入来运行智能体工作流
    需要先看state是如何进行初始化的，以及state的各个属性是如何被赋值的

    Args:
        user_input_messages: 用户的请求列表
        debug: If True, enables debug level logging

    Returns:
        工作量完成以后的最终state
    """
    # 如果任务类型是创建智能体
    if task_type == TaskType.AGENT_FACTORY:
        graph = agent_factory_graph()
    else:
        graph = build_graph()
    if not user_input_messages:
        raise ValueError("输入不能为空")

    if debug:
        enable_debug_logging()

#=========================================================state的初始化=========================================================
    logger.info(f"正在依据用户的输入启动工作流: {user_input_messages}")

    workflow_id = str(uuid.uuid4())# 生成一个唯一的workflow_id

    # 定义智能体描述和工具描述的模板
    TEAM_MEMBERS_DESCRIPTION_TEMPLATE = """
    - **`{agent_name}`**: {agent_description}
    """
    TOOLS_DESCRIPTION_TEMPLATE = """
    - **`{tool_name}`**: {tool_description}
    """
    TOOLS_DESCRIPTION = ""# 工具描述
    TEAM_MEMBERS_DESCRIPTION = DEFAULT_TEAM_MEMBERS_DESCRIPTION# 默认的智能体描述
    TEAM_MEMBERS = ["agent_factory"]# 智能体列表，默认包含agent_factory智能体

    # 这里的agent_manager就是AgentManager类的示例，同时运行了initialize方法，所以agent_manager.available_agents中已经包含了目前所有的智能体
    # 选择需要使用的智能体:(1)share智能体，(2)coor_agents中的智能体，(3)user_id对应的智能体，(4)agent_factory智能体
    for agent in agent_manager.available_agents.values():
        if agent.user_id == "share":
            TEAM_MEMBERS.append(agent.agent_name)

        if agent.user_id == user_id or agent.agent_name in coor_agents:
            TEAM_MEMBERS.append(agent.agent_name)

        # 如果智能体的user_id不是share，那么添加新的智能体描述到TEAM_MEMBERS_DESCRIPTION
        if agent.user_id != "share":
            MEMBER_DESCRIPTION = TEAM_MEMBERS_DESCRIPTION_TEMPLATE.format(agent_name=agent.agent_name, agent_description=agent.description)
            TEAM_MEMBERS_DESCRIPTION += '\n' + MEMBER_DESCRIPTION

    # 拼接所有的工具描述
    for tool_name, tool in agent_manager.available_tools.items():
        TOOLS_DESCRIPTION += '\n' + TOOLS_DESCRIPTION_TEMPLATE.format(tool_name=tool_name,tool_description=tool.description)

    global coordinator_cache
    coordinator_cache = []
    global is_handoff_case
    is_handoff_case = False

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
            async for event_data in _process_workflow(
                graph,
                {
                    "user_id": user_id,# 用户的ID
                    "TEAM_MEMBERS": TEAM_MEMBERS,# 智能体name组成的列表
                    "TEAM_MEMBERS_DESCRIPTION": TEAM_MEMBERS_DESCRIPTION,# 智能体拼接的字符串描述
                    "TOOLS": TOOLS_DESCRIPTION,# 拼接后的工具描述
                    "messages": user_input_messages,# 用户的messages列表
                    "deep_thinking_mode": deep_thinking_mode,# 是否开启深度思考模式
                    "search_before_planning": search_before_planning,# 是否在规划之前进行搜索
                },
                workflow_id,# 工作流的ID
            ):
                yield event_data

async def _process_workflow(
    workflow, 
    initial_state: Dict[str, Any], 
    workflow_id: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """处理自定义工作流的事件流"""
    current_node = None

    yield {
        "event": "start_of_workflow",
        "data": {"workflow_id": workflow_id, "input": initial_state["messages"]},
    }
    
    try:
        current_node = workflow.start_node# 从开始节点开始
        state = State(**initial_state)# 初始化状态对象
    
        
        while current_node != "__end__":# 直到出现__end__节点为止
            agent_name = current_node
            logger.info(f"Started node: {agent_name}")
            
            yield {
                "event": "start_of_agent",
                "data": {
                    "agent_name": agent_name,
                    "agent_id": f"{workflow_id}_{agent_name}_1",
                },
            }# 通过yield产生不同类型的event
            node_func = workflow.nodes[current_node]

            command = await node_func(state)
            
            if hasattr(command, 'update') and command.update:
                for key, value in command.update.items():
                    if key != "messages":
                        state[key] = value
                    
                    if key == "messages" and isinstance(value, list) and value:
                        state["messages"] += value
                        last_message = value[-1]
                        if 'content' in last_message:
                            if agent_name == "coordinator":
                                content = last_message["content"]
                                if content.startswith("handover"):
                                    # mark handoff, do not send maesages
                                    global is_handoff_case
                                    is_handoff_case = True
                                    continue
                            if agent_name in ["planner", "coordinator", "agent_proxy"]:
                                content = last_message["content"]
                                chunk_size = 10  # send 10 words for each chunk
                                for i in range(0, len(content), chunk_size):
                                    chunk = content[i:i+chunk_size]
                                    if 'processing_agent_name' in state:
                                        agent_name = state['processing_agent_name']
                    
                                    yield {
                                        "event": "messages",
                                        "agent_name": agent_name,
                                        "data": {
                                            "message_id": f"{workflow_id}_{agent_name}_msg_{i}",
                                            "delta": {"content": chunk},
                                        },
                                    }
                                    await asyncio.sleep(0.01)

                    if agent_name == "agent_factory" and key == "new_agent_name":
                        yield {
                            "event": "new_agent_created",
                            "agent_name": value,
                            "data": {
                                "new_agent_name": value,
                                "agent_obj": agent_manager.available_agents[value],
                            },
                        }
                                                
                            

            yield {
                "event": "end_of_agent",
                "data": {
                    "agent_name": agent_name,
                    "agent_id": f"{workflow_id}_{agent_name}_1",
                },
            }
            
            next_node = command.goto            
            current_node = next_node
            
        yield {
            "event": "end_of_workflow",
            "data": {
                "workflow_id": workflow_id,
                "messages": [
                    {"role": "user", "content": "workflow completed"}
                ],
            },
        }
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"Error in Agent workflow: {str(e)}")
        yield {
            "event": "error",
            "data": {
                "workflow_id": workflow_id,
                "error": str(e),
            },
        }



