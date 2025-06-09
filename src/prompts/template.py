import os
import re
from datetime import datetime
import copy
from langchain_core.prompts import PromptTemplate
from langgraph.prebuilt.chat_agent_executor import AgentState
from src.utils.path_utils import get_project_root
from langchain_core.messages import HumanMessage



def get_prompt_template(prompt_name: str) -> str:
    prompts_dir = get_project_root() / "src" / "prompts"

    # 根据传递的prompt_name，读取对应的prompt的md文件转化为字符串
    template = open(os.path.join(prompts_dir, f"{prompt_name}.md")).read()
    
    # 找到prompt中所有的变量名（格式为 <<VAR>>）
    variables = re.findall(r"<<([^>>]+)>>", template)
    
    # 将花括号进行转义
    template = template.replace("{", "{{").replace("}", "}}")
    # 将`<<VAR>>`替换为`{VAR}`
    template = re.sub(r"<<([^>>]+)>>", r"{\1}", template)
    
    # template表示后处理过后的提示词模版字符串，variables是变量组成的列表
    return template, variables


def apply_prompt_template(prompt_name: str, state: AgentState, template:str=None) -> list:
    state = copy.deepcopy(state)
    messages = []
    # 将messages全部转化为列表的形式并只获取user和assistant的messages（删除掉system）
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, dict) and 'role' in msg:
            if msg["role"] == "user":
                messages.append({"role": "user", "content": msg["content"]})
            else:
                messages.append({"role": "assistant", "content": msg["content"]})
    state["messages"] = messages
    
    # 根据当前的任务类型获取提示词模版（舍弃掉模版中的变量列表）
    _template, _ = get_prompt_template(prompt_name) if not template else template
    system_prompt = PromptTemplate(
        input_variables=["CURRENT_TIME"],
        template=_template,
    ).format(CURRENT_TIME=datetime.now().strftime("%a %b %d %Y %H:%M:%S %z"), **state)# 利用current_time和state中的参数来填充提示词模版

    return [{"role": "system", "content": system_prompt}] + messages# 合并为新的messages列表

def decorate_prompt(template: str) -> list:
    variables = re.findall(r"<<([^>>]+)>>", template)
    template = template.replace("{", "{{").replace("}", "}}")
    # Replace `<<VAR>>` with `{VAR}`
    template = re.sub(r"<<([^>>]+)>>", r"{\1}", template)
    if "CURRENT_TIME" not in template:
        template = "Current time: {CURRENT_TIME}\n\n" + template
    return template

def apply_prompt(state: AgentState, template:str=None) -> list:
    template = decorate_prompt(template)
    _prompt = PromptTemplate(
        input_variables=["CURRENT_TIME"],
        template=template,
    ).format(CURRENT_TIME=datetime.now().strftime("%a %b %d %Y %H:%M:%S %z"), **state)
    return _prompt