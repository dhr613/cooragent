from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from .mcp_types import Tool
from enum import Enum, unique
from typing_extensions import TypedDict
from langgraph.graph import MessagesState


@unique
class Lang(str, Enum):
    EN = "en"
    ZH = "zh"
    JP = "jp"
    SP = 'sp'
    DE = 'de'


class LLMType(str, Enum):
    BASIC = "basic"
    REASONING = "reasoning"
    VISION = "vision"
    CODE = 'code'


class TaskType(str, Enum):
    AGENT_FACTORY = "agent_factory"
    AGENT_WORKFLOW = "agent_workflow"
    
    
class Agent(BaseModel):
    """Definition for an agent the client can call."""
    user_id: str
    """用户的ID"""
    agent_name: str
    """智能体的名称"""
    nick_name: str
    """智能体的ID"""
    description: str
    """智能体的描述"""
    llm_type: LLMType
    """智能体使用的模型的类型，basic，code还是reasoning"""
    selected_tools: List[Tool]
    """智能体可以使用的工具列表"""
    prompt: str
    """该智能体所使用的提示词"""
    model_config = ConfigDict(extra="allow")

    
class AgentMessage(BaseModel):
    content: str
    role: str
    
class AgentRequest(BaseModel):
    user_id: str
    lang: Lang
    messages: List[AgentMessage]
    debug: bool
    deep_thinking_mode: bool
    search_before_planning: bool
    task_type: TaskType
    coor_agents: Optional[list[str]]
    
class listAgentRequest(BaseModel):
    user_id: Optional[str]
    match: Optional[str]
    

class Router(TypedDict):
    """Worker to route to next. If no workers needed, route to FINISH."""
    next: str


class State(MessagesState):
    """State for the agent system, extends MessagesState with next field."""
    TEAM_MEMBERS: list[str]
    TEAM_MEMBERS_DESCRIPTION: str
    user_id: str
    next: str
    full_plan: str
    deep_thinking_mode: bool
    search_before_planning: bool


class RemoveAgentRequest(BaseModel):
    user_id: str
    agent_name: str
