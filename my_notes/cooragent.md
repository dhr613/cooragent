# cooragent

class AgentManeger(**src.manager.agent**)：用来对智能体进行管理

- \_\_init_\_\:
  - tools_dir：工具文件的路径
  - agents_dir：智能体的路径
  - prompt_dir：提示词的路径
- <font color="#dd0000">def</font> initialize：初始化智能体与工具
  - <font color="#dd0000">def</font> _load_agents
    - <font color="#dd0000">def</font> _load_default_agent
      - <font color="#dd0000">def</font> _create_agent_by_prebuilt：预创建一个智能体，需要添加智能体以下的信息，每次都会生成一个Agent的实力，利用Agent的示例中的属性来保存智能体的信息
        - 名称(agent_name，str)
        - 别称(nickname，str)
        - 描述(description，str)
        - 用户ID(user_id，str)
        - 选择的工具列表(是一个Tool属性组成的列表)
          - **src.interface.mcp_types**
          - 是一个集成了BaseModel的类：name(str)，description(str)，model_config(ConfigDict，这里面规定了众多的其他属性值)
        - 提示词(prompt，str)
        - 该函数不会返回任何结果，但是会在本地的agent_path下生成一个独属于该Agent的json文件来保存属性，同时记录所有生成的agent的name
      - 用上面的函数来构造四个默认的智能体并保存在本地
        - agent_name="researcher"，user_id="share"(表示这个工具是共有的，也就是基础智能体)绑定工具为tavily和crawl_tool，该智能体是用来获取信息的
        - agent_name="coder"，user_id="share"，绑定工具为python_repl_tool和bash_tool，该智能体是用来实现python和bash的软件工程任务
        - agent_name="browser"，user_id="share"，绑定工具为browser_tool，该智能体的作用是与浏览器进行交互，例如爬取特定网页的内容
        - agent_name="reporter"，user_id="share"，绑定工具无，该智能体的作用是用来根据所掌握的信息来撰写报告
  - <font color="#dd0000">def</font> load_tools：添加可以使用的工具的键值对
    - bash_tool.name：bash_tool，处理bash代码的工具
    - brower_tool.name：brower_tool，与网址进行交互的工具（可选择删除）
    - crawl_tool.name：crawl_tool，爬取网页数据的工具
    - python_repl_tool.name：python_repl_tool，处理python代码的工具
    - tavily_tool.name：tavily_tool，进行网页搜索的工具
    - mcp工具：<font color="#dd0000">def</font> mcp_client_config(**src.manger.mcp**)



---

state的初始化(**src.workflow.process**)

- user_id：发送请求的时候设定
- TEAM_MEMBERS：可以使用的智能体列表
  - 自带一个"agent_factory"
  - 遍历每一个可以使用的智能体
    - 添加所有user_id="share"的智能体的agent_name
    - 添加所有用户想要的智能体的agent_name（通过发送请求时候设定的user_id和coor_agents中获取）
- TEAM_DESCRIPTION：一个字符串，由上面选择的所有智能体的agent_name和description拼接的形成的字符串，表示对所有智能体的描述
- TOOL：一个字符串，所有可用的tool_name和tool_description拼接的字符串，表示对所有工具的描述
- messages：输入的消息列表
- deep_thinking_mode：bool，是否进行深度思考
- search_before_planning：bool，在制定计划前是否进行网络检索



run_agent_workflow(**src.workflow.process**)

- agent_factory_graph(langgraph)
  - <font color="#dd0000">def</font> coordinator_node(node:coordinator)：协调员节点，通过用户的提问来决定只是简单的闲聊，还是进入下一个节点（以llm是否输出handover_to_planner()为判断依据)
    - <font color="#dd0000">def</font> apply_prompt_template(**src.prompts.template**):
      - 将state中的所有的消息形式都转化为messages列表的形式，同时只保留human和ai的messages
      - <font color="#dd0000">def</font> get_prompt_template：
        - 确定项目的根目录
        - 根据传递的prompt_name（此时为coordinator，协调员）读取对应的prompt的md文件
        - 返回md文件中的[prompt][F:\cooragent\coordinator.md]和prompt中的变量名（CURRENT_TIME，目前的时候，由time来实时获取，其他变量名可以通过state中的属性来获取）
      - 将prompt作为system message添加的messages列表的最前面并返回该messages列表
    - <font color="#dd0000">def</font> get_llm_by_type(**src.llm.llm**):根据传递的llm_type参数（llm_type由prompt_name来确定，当prompt_name=coordinator时，llm_typ=basic，也就是LangchainOpenAI）来返回对应的langchain下的模型实例
      - 如果用户的问题是闲聊，那么就会返回一个闲聊的简单回答（同时goto指向end，）如果是由具体的需求，那么会返回一个"handover_to_planner()"字符串（同时goto指向“planner”）
      - Command更新消息state中的messags与agent_name为"coordinator"
  - <font color="#dd0000">def</font> planner_node(node:planner)：根据用户的需求生成一个json字符串，来确定用户的需求需要哪些agent来实现，并提供对应agent的信息
    - <font color="#dd0000">def</font> apply_prompt_template(**已出现**):此时的prompt_name是"planner",获取对应的[prompt][F:\cooragent\planner.md]（planner中prompt会使用state中的TEAM_MEMBERS和TEAM_MEMBERS_DESCRIPTION变量来填充相关信息，以此来生成agent信息）作为system messages并返回messages列表
    - <font color="#dd0000">def</font> get_llm_by_type(**已出现**):根据prompt_name（此时为planner）选择对应的模型类型（reasoning，为LangchainDeepSeek），并将messags列表作为输出，返回对应的响应字符串
    - 如果state中规定了"deep_thinking_mode"参数，那么强制使用推理模型
    - 如果state中固定了"search_before_planning"参数，那么首先会利用tavily检索器去根据用户的提问来进行一次检索，然后将检索的结果添加到messages列表中最后一条消息的content字符串中（也就是用户的message）
    - 根据提示规则会返回一个json格式的字符串，经过后处理以后利用json.loads来解析获取结构化的信息
    - 将解析之前的字符串添加到state中的messages列表中，如果结构化解析成功，则goto到"publisher"节点，如果解析失败，则goto到"end"节点
  - <font color="#dd0000">def</font> publisher_node(node:publisher)
    - <font color="#dd0000">def</font> apply_prompt_template(**已出现**):此时的prompt_name是"publisher"，获取对应的[prompt][F:\cooragent\publisher.md]
