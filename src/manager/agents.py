import asyncio
from langgraph.prebuilt import create_react_agent
from src.interface.mcp_types import Tool
from src.prompts import apply_prompt_template, get_prompt_template

from src.tools import (
    bash_tool,
    browser_tool,
    crawl_tool,
    python_repl_tool,
    tavily_tool,
)

from src.llm.llm import get_llm_by_type
from src.llm.agents import AGENT_LLM_MAP
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pathlib import Path
from src.interface.agent_types import Agent
from src.service.env import USR_AGENT, USE_BROWSER,USE_MCP_TOOLS
from src.manager.mcp import mcp_client_config
import logging
import re

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

class NotFoundAgentError(Exception):
    """当agent没有找到"""
    pass

class NotFoundToolError(Exception):
    """当工具没有找到"""
    pass

class AgentManager:
    def __init__(self, tools_dir, agents_dir, prompt_dir):
        for path in [tools_dir, agents_dir, prompt_dir]:
            if not path.exists():
                logger.info(f"路径 {path} 不存在，在初始化agent manager时，将创建... \n")
                path.mkdir(parents=True, exist_ok=True)
                
        self.tools_dir = Path(tools_dir)# 工具json们所在的文件夹
        self.agents_dir = Path(agents_dir)# 智能体json们所在的文件夹
        self.prompt_dir = Path(prompt_dir)# 提示词json们所在的文件夹

        if not self.tools_dir.exists() or not self.agents_dir.exists() or not self.prompt_dir.exists():
            raise FileNotFoundError("提供的目录之一不存在。")
        self.available_agents = {}# 存放可使用的智能体
        self.available_tools = {}# 存放可使用的工具

    async def initialize(self, user_agent_flag=USR_AGENT):
        """异步初始化AgentManager，加载agents和tools"""
        await self._load_agents(user_agent_flag)# 向self.available_agents中添加默认的智能体
        await self.load_tools()# 向self.available_tools中添加默认的工具
        logger.info(f"AgentManager初始化完成。 共有{len(self.available_agents)} 个agents 和 {len(self.available_tools)} 个tools 可用。")

    def _create_agent_by_prebuilt(self, user_id: str, name: str, nick_name: str, llm_type: str, tools: list[tool], prompt: str, description: str):
        def _create(user_id: str, name: str, nick_name: str, llm_type: str, tools: list[tool], prompt: str, description: str):
            _tools = []
            for tool in tools:
                _tools.append(Tool(
                    name=tool.name,
                    description=tool.description,
                ))
            
            _agent = Agent(
                agent_name=name,
                nick_name=nick_name,
                description=description,
                user_id=user_id,
                llm_type=llm_type,
                selected_tools=_tools,
                prompt=str(prompt)
            )
        
            self._save_agent(_agent)
            return _agent
        
        _agent = _create(user_id, name, nick_name, llm_type, tools, prompt, description)
        self.available_agents[name] = _agent
        return


    async def load_mcp_tools(self):
        mcp_client = MultiServerMCPClient(mcp_client_config())
        mcp_tools = await mcp_client.get_tools()
        for _tool in mcp_tools:
            self.available_tools[_tool.name] = _tool
                    
    async def load_tools(self):
        # 向self.available_tools中添加默认的工具，这些工具都是默认加载的agent所绑定的工具
        self.available_tools.update({
            bash_tool.name: bash_tool,# 添加bash_tool
            browser_tool.name: browser_tool,# 添加browser_tool
            crawl_tool.name: crawl_tool,# 添加crawl_tool
            python_repl_tool.name: python_repl_tool,# 添加python_repl_tool
            tavily_tool.name: tavily_tool,# 添加tavily_tool
        })
        # 如果设置了不使用浏览器，那么删除browser_tool
        if not USE_BROWSER:
            del self.available_tools[browser_tool.name]    
        # 如果设置了使用mcp工具，那么加载mcp工具
        if USE_MCP_TOOLS:
            await self.load_mcp_tools()

    def _save_agent(self, agent: Agent, flush=False):
        agent_path = self.agents_dir / f"{agent.agent_name}.json"
        agent_prompt_path = self.prompt_dir / f"{agent.agent_name}.md"
        if not flush and agent_path.exists():
            return
        with open(agent_path, "w") as f:
            f.write(agent.model_dump_json())
        with open(agent_prompt_path, "w") as f:
            f.write(agent.prompt)

        logger.info(f"智能体 {agent.agent_name} 已存放")
        
    def _remove_agent(self, agent_name: str):
        agent_path = self.agents_dir / f"{agent_name}.json"
        agent_prompt_path = self.prompt_dir / f"{agent_name}.md"

        try:
            agent_path.unlink(missing_ok=True)  # delete json file
            logger.info(f"Removed agent definition file: {agent_path}")
        except Exception as e:
            logger.error(f"Error removing agent definition file {agent_path}: {e}")

        try:
            agent_prompt_path.unlink(missing_ok=True) 
            logger.info(f"Removed agent prompt file: {agent_prompt_path}")
        except Exception as e:
            logger.error(f"Error removing agent prompt file {agent_prompt_path}: {e}")

        try:
            if agent_name in self.available_agents:
                del self.available_agents[agent_name] 
                logger.info(f"Removed agent '{agent_name}' from available agents.")
        except Exception as e:
             logger.error(f"Error removing agent '{agent_name}' from available_agents dictionary: {e}")
    
    async def _load_agent(self, agent_name: str, user_agent_flag: bool=False):
        agent_path = self.agents_dir / f"{agent_name}.json"
        if not agent_path.exists():
            raise FileNotFoundError(f"agent {agent_name} not found.")
        with open(agent_path, "r") as f:
            json_str = f.read()
            _agent = Agent.model_validate_json(json_str)
            if _agent.user_id == 'share':
                self.available_agents[_agent.agent_name] = _agent
            elif user_agent_flag:
                self.available_agents[_agent.agent_name] = _agent

            return
        
    async def _list_agents(self, user_id: str = None, match: str = None):
        agents = [agent for agent in self.available_agents.values()]
        if user_id:
            agents = [agent for agent in agents if agent.user_id == user_id]
        if match:
            agents = [agent for agent in agents if re.match(match, agent.agent_name)]
        return agents

    def _edit_agent(self, agent: Agent):
        try:
            _agent = self.available_agents[agent.agent_name]
            _agent.nick_name = agent.nick_name
            _agent.description = agent.description
            _agent.selected_tools = agent.selected_tools
            _agent.prompt = agent.prompt
            _agent.llm_type = agent.llm_type
            self._save_agent(_agent, flush=True)
            return "success"
        except Exception as e:
            raise NotFoundAgentError(f"agent {agent.agent_name} not found.")
    
    def _save_agents(self, agents: list[Agent], flush=False):
        for agent in agents:
            self._save_agent(agent, flush)  
        return
    
    async def _load_default_agents(self):
        # _create_agent_by_prebuilt作用有以下几点：
        # 创建一个Agent类型（继承BaseModel）的示例，这个示例的各个属性来保存该智能体的各个属性
        # 将每个Agent的实例以智能体的名称分别存放它的所有属性和提示词

        # 添加默认智能体1,绑定了tavily_tool和crawl_tool，主要用于网络检索
        self._create_agent_by_prebuilt(user_id="share", 
                                        name="researcher", 
                                        nick_name="researcher", 
                                        llm_type=AGENT_LLM_MAP["researcher"], 
                                        tools=[tavily_tool, crawl_tool], 
                                        prompt=get_prompt_template("researcher"),# 这个函数会根据输入的参数去获取对应的prompt，返回一个元组，0表示提示词模版，1表示提示词中的所有变量组成的列表
                                        description="这个智能体擅长使用搜索引擎和网络爬虫进行研究任务。它可以根据关键词搜索信息，爬取特定URL以提取内容，并将发现综合成全面的报告。这个智能体在从多个来源收集信息、验证相关性和可信度以及基于收集的数据提出结构化结论方面表现出色。"),
        
        # 添加默认智能体2，绑定了python_repl_tool和bash_tool，主要用于代码生成和执行
        self._create_agent_by_prebuilt(user_id="share", 
                                        name="coder", 
                                        nick_name="coder", 
                                        llm_type=AGENT_LLM_MAP["coder"], 
                                        tools=[python_repl_tool, bash_tool], 
                                        prompt=get_prompt_template("coder"),
                                        description="这个代理专门使用Python和bash脚本进行软件工程任务。它可以分析需求，实施高效的解决方案，并提供清晰的文档。该代理擅长数据分析、算法实现、系统资源管理和环境查询。它遵循最佳实践，处理边缘情况，并在需要时将Python与bash集成起来，以全面解决问题。"),
        
        # 添加了默认智能体3，绑定了brower_tool，主要用于与指定网站交互，比如搜索，点击，填写表单，爬取内容等
        self._create_agent_by_prebuilt(user_id="share", 
                                        name="browser", 
                                        nick_name="browser", 
                                        llm_type=AGENT_LLM_MAP["browser"], 
                                        tools=[browser_tool], 
                                        prompt=get_prompt_template("browser"), 
                                        description="他的代理专门用于与网页浏览器交互。它可以导航到网站，执行诸如单击、键入和滚动等操作，并从网页中提取信息。该代理擅长处理搜索特定网站、与网页元素交互以及收集在线数据等任务。它能够进行登录、填写表单、单击按钮和抓取内容等操作。"),
    
        # 添加了默认智能体4，不绑定任何工具，主要用于生成纯文本的报告，比如总结，分析，结论等
        self._create_agent_by_prebuilt(user_id="share", 
                                        name="reporter", 
                                        nick_name="reporter", 
                                        llm_type=AGENT_LLM_MAP["reporter"], 
                                        tools=[], 
                                        prompt=get_prompt_template("reporter"), 
                                        description="该代理专门根据提供的信息和可验证的事实创建清晰、全面的报告。它客观地呈现数据，逻辑地组织信息，并使用专业语言突出关键发现。该代理以执行摘要、详细分析和可行结论的形式构建报告，同时保持严格的数据完整性，绝不捏造信息。 ")

                    
    async def _load_agents(self, user_agent_flag):
        await self._load_default_agents()# 先加载默认的智能体到self.available_agents中
        load_tasks = []

        # 遍历agent_dir下的所有json文件，
        for agent_path in self.agents_dir.glob("*.json"):
            agent_name = agent_path.stem
            if agent_name not in self.available_agents.keys():
                # 将存在于本地但是不在sefl.available_agents中的智能体按照要求加载到self.available_agents中
                # （self._load_agent并未运行，因为它是一个异步函数，所以添加到列表中的是协程函数，后面会通过asyncio.gather进行并发调用）
                load_tasks.append(self._load_agent(agent_name, user_agent_flag))
        
        # 如果设置了不使用浏览器，那么删除browser智能体
        if not USE_BROWSER and "browser" in self.available_agents:
            del self.available_agents["browser"]
            
        # 如果load_tasks不为空，那么并发添加智能体到self.available_agents中
        if load_tasks:
            results = await asyncio.gather(*load_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                 if isinstance(result, FileNotFoundError):
                      logger.warning(f"在批量加载智能体时，文件未找到: {load_tasks[i]}. 错误: {result}")
                 elif isinstance(result, Exception):
                      logger.error(f"在批量加载智能体时，发生错误: {load_tasks[i]}. 错误: {result}")
        return   
    
    async def _list_default_tools(self):
        tools = []
        for tool_name, tool in self.available_tools.items():
            tools.append(Tool(
                name=tool_name,
                description=tool.description,
            ))
        return tools
    
    async def _list_default_agents(self):
        agents = [agent for agent in self.available_agents.values() if agent.user_id == "share"]
        return agents
    
from src.utils.path_utils import get_project_root

tools_dir = get_project_root() / "store" / "tools"
agents_dir = get_project_root() / "store" / "agents"
prompts_dir = get_project_root() / "store" / "prompts"

agent_manager = AgentManager(tools_dir, agents_dir, prompts_dir)
asyncio.run(agent_manager.initialize())
