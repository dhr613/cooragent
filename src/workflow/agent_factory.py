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
    """Node for the create agent agent that creates a new agent."""
    logger.info("Agent Factory Start to work \n")
    messages = apply_prompt_template("agent_factory", state)
    response = (
        get_llm_by_type(AGENT_LLM_MAP["agent_factory"])
        .with_structured_output(AgentBuilder)
        .invoke(messages)
    )
    
    tools = [agent_manager.available_tools[tool["name"]] for tool in response["selected_tools"]]

    agent_manager._create_agent_by_prebuilt(
        user_id=state["user_id"],
        name=response["agent_name"],
        nick_name=response["agent_name"],
        llm_type=response["llm_type"],
        tools=tools,
        prompt=response["prompt"],
        description=response["agent_description"],
    )
    
    state["TEAM_MEMBERS"].append(response["agent_name"])

    return Command(
        update={
            "messages": [
                {"content":f'New agent {response["agent_name"]} created. \n', "tool":"agent_factory", "role":"assistant"}
            ],
            "new_agent_name": response["agent_name"],
            "agent_name": "agent_factory",
        },
        goto="__end__",
    )


async def publisher_node(state: State) -> Command[Literal["agent_factory", "agent_factory", "__end__"]]:
    """决定下一个应由哪个代理行动的发布者节点。"""
    logger.info("发布者正在评估下一个行动... \n")
    messages = apply_prompt_template("publisher", state)
    response = await (
        get_llm_by_type(AGENT_LLM_MAP["publisher"])
        .with_structured_output(Router)
        .ainvoke(messages)
    )
    agent = response["next"]
    
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
    llm = get_llm_by_type(AGENT_LLM_MAP["planner"])
    if state.get("deep_thinking_mode"):
        llm = get_llm_by_type("reasoning")
    if state.get("search_before_planning"):
        searched_content = tavily_tool.invoke({"query": state["messages"][-1]["content"]})# 调用tavily_tool，获取相关搜索结果
        messages = deepcopy(messages)
        messages[-1]["content"] += f"\n\n# 相关搜索结果\n\n{json.dumps([{'titile': elem['title'], 'content': elem['content']} for elem in searched_content], ensure_ascii=False)}"
    
    response = await llm.ainvoke(messages)# 调用planner的llm模型，获取response
    content = clean_response_tags(response.content)

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
    """与用户沟通的协调节点。"""
    logger.info("协调员正在谈话... \n")
    messages = apply_prompt_template("coordinator", state)# 获取coordinator的messages列表
    response = await get_llm_by_type(AGENT_LLM_MAP["coordinator"]).ainvoke(messages)# 调用coordinator的llm模型，获取response
    goto = "__end__"
    if "handover_to_planner" in response.content:# 如果response中包含handover_to_planner，则跳转到planner节点
        goto = "planner"
        
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
