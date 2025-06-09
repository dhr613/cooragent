import logging
import json
from copy import deepcopy
from typing import Literal
from langgraph.types import Command

from src.llm.llm import get_llm_by_type
from src.llm.agents import AGENT_LLM_MAP
from src.prompts.template import apply_prompt_template
from src.tools.search import tavily_tool
from src.interface.agent_types import State, Router
from src.interface.serialize_types import AgentBuilder
from src.manager import agent_manager
from src.workflow.graph import AgentWorkflow
from src.utils.content_process import clean_response_tags

logger = logging.getLogger(__name__)

RESPONSE_FORMAT = "Response from {}:\n\n<response>\n{}\n</response>\n\n*Please execute the next step.*"

async def agent_factory_node(state: State) -> Command[Literal["publisher","__end__"]]:
    """这个节点用来创建新的代理"""
    logger.info("agent_factory开始工作 \n")
    messages = apply_prompt_template("agent_factory", state)
    '''
    agent_factory中的prompt中有两个变量:(1)current_time,(2)tools(可以使用的工具列表)，它要求你生成一个AgentBuilder类型的示例，

    interface Tool {
        name: string;
        description: string;
        }

    interface AgentBuilder {
        agent_name: string;
        agent_description: string;
        thought: string;
        llm_type: string;
        selected_tools: Tool[];
        prompt: string;
        }

    
    '''
    response = (
        get_llm_by_type(AGENT_LLM_MAP["agent_factory"])
        .with_structured_output(AgentBuilder)
        .invoke(messages)
    )
    
    # 将工具的名称转换为工具的实例
    tools = [agent_manager.available_tools[tool["name"]] for tool in response["selected_tools"]]

    agent_manager._create_agent_by_prebuilt(
        user_id=state["user_id"],
        name=response["agent_name"],
        nick_name=response["agent_name"],
        llm_type=response["llm_type"],
        tools=tools,
        prompt=response["prompt"],
        description=response["agent_description"],
    )# 创建一个新的智能体
    
    state["TEAM_MEMBERS"].append(response["agent_name"])# 更新TEAM_MEMBERS列表

    return Command(
        update={
            "messages": [
                {"content":f'新的智能体 {response["agent_name"]} 已经被创建 \n', "tool":"agent_factory", "role":"assistant"}
            ],
            "new_agent_name": response["agent_name"],
            "agent_name": "agent_factory",
        },
        goto="__end__",
    )


async def publisher_node(state: State) -> Command[Literal["agent_factory", "agent_factory", "__end__"]]:
    """这是个路由节点，明确下一个执行的节点"""
    logger.info("publisher正在评估下一个行动... \n")
    messages = apply_prompt_template("publisher", state)
    response = await (
        get_llm_by_type(AGENT_LLM_MAP["publisher"])
        .with_structured_output(Router)# 结构化输出，返回下一个节点的键值对:{"next":node_name}
        .ainvoke(messages)
    )
    agent = response["next"]# 指向下一个节点
    
    # 这里出现了参数缺失的问题，我个人感觉这个graph的任务就是创建新的智能体，所以这类的goto就应该只指向agent_factory
    if agent == "FINISH":
        goto = "__end__"
        logger.info("工作流完成 \n")
        return Command(goto=goto, update={"next": goto})
    elif agent != "agent_factory":
        logger.info(f"发布者委托给: {agent}")
        return Command(goto=goto, update={"next": agent})
    else:
        goto = "agent_factory"
        logger.info(f"发布者委托给: {agent}")
        return Command(goto=goto, update={"next": agent})


async def planner_node(state: State) -> Command[Literal["publisher", "__end__"]]:
    """计划节点，为任务生成完整的计划"""
    logger.info("计划节点正在生成完整的计划... \n")
    messages = apply_prompt_template("planner", state)# 获取planner的messages列表
    '''
    palnner的prompt才是重点，它里面有三个变量:(1)current_time ,(2)team_members（智能体名称的列表）,(3)team_members_description（所有智能体的描述）

    它要求你根据用户的请求，生成一个嵌套的json：
    ```ts
        interface NewAgent {
        name: string;
        role: string;
        capabilities: string;
        contribution: string;
        }

        interface Step {
        agent_name: string;
        title: string;
        description: string;
        note?: string;
        }

        interface PlanWithAgents {
        thought: string; # 复述用户的请求（加入自己的思考）
        title: string; # 计划的总标题
        new_agents_needed: NewAgent[]; # 如果当前智能体不能完成任务，那么需要创建新的智能体来完成任务，这里写清楚需要创建的智能体（只能创建一个智能体）
        steps: Step[]; # 分布计划
        }
    ```

    '''
    llm = get_llm_by_type(AGENT_LLM_MAP["planner"])# 获取模型
    if state.get("deep_thinking_mode"):
        llm = get_llm_by_type("reasoning")
    if state.get("search_before_planning"):
        searched_content = tavily_tool.invoke({"query": state["messages"][-1]["content"]})# 调用tavily_tool，获取相关搜索结果
        messages = deepcopy(messages)
        messages[-1]["content"] += f"\n\n# 相关搜索结果\n\n{json.dumps([{'titile': elem['title'], 'content': elem['content']} for elem in searched_content], ensure_ascii=False)}"
    
    response = await llm.ainvoke(messages)# 调用planner的llm模型，获取response
    content = clean_response_tags(response.content)# 对响应进行后处理

    goto = "publisher"
    try:
        json.loads(content)
    except json.JSONDecodeError:
        logger.warning("计划节点的响应不是有效的JSON")
        goto = "__end__"

    return Command(
        update={
            "messages": [{"content":content, "tool":"planner", "role":"assistant"}],
            "agent_name": "planner",
            "full_plan": content,
        },
        goto=goto,
    )


async def coordinator_node(state: State) -> Command[Literal["planner", "__end__"]]:
    """与用户沟通的协调节点。用来决定是简单对话还是需要规划"""
    logger.info("协调员正在决定是简单对话还是需要规划... \n")
    messages = apply_prompt_template("coordinator", state)# 获取coordinator的messages列表
    response = await get_llm_by_type(AGENT_LLM_MAP["coordinator"]).ainvoke(messages)# 调用coordinator的llm模型，获取response
    goto = "__end__"
    if "handover_to_planner" in response.content:# 如果response中包含handover_to_planner，则跳转到planner节点
        goto = "planner"
    
    # 利用Command更新state，其中agent_name并没有在state初始化的时候出现，但是update会为没有在state中出现的元素进行更新，后面的state就都有了
    # messages被设定为add，agent_name则默认为覆盖
    return Command(
        update={
            "messages": [{"content":response.content, "tool":"coordinator", "role":"assistant"}],
            "agent_name": "coordinator",
        },
        goto=goto,
    )
def agent_factory_graph():
    workflow = AgentWorkflow()    
    workflow.add_node("coordinator", coordinator_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("publisher", publisher_node)
    workflow.add_node("agent_factory", agent_factory_node)
    
    workflow.set_start("coordinator")    
    return workflow.compile()
