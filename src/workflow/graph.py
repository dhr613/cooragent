from typing import Dict, Callable, List, Optional
from src.interface.agent_types import State
from langgraph.types import Command

NodeFunc = Callable[[State], Command]

class AgentWorkflow:
    '''
    该类可以简化添加节点和边的流程
    '''
    def __init__(self):
        self.nodes: Dict[str, NodeFunc] = {}
        self.edges: Dict[str, List[str]] = {}
        self.start_node: Optional[str] = None
        
    def add_node(self, name: str, func: NodeFunc) -> None:
        '''
        添加节点
        '''
        self.nodes[name] = func
        
    def add_edge(self, source: str, target: str) -> None:
        '''
        添加边
        '''
        if source not in self.edges:
            self.edges[source] = []
        self.edges[source].append(target)
        
    def set_start(self, node: str) -> None:
        '''
        设置起始节点
        '''
        self.start_node = node
        
    def compile(self):
        '''
        编译工作流
        '''
        return CompiledWorkflow(self.nodes, self.edges, self.start_node)

class CompiledWorkflow:
    def __init__(self, nodes: Dict[str, NodeFunc], edges: Dict[str, List[str]], start_node: str):
        self.nodes = nodes
        self.edges = edges
        self.start_node = start_node
        
    def invoke(self, state: State) -> State:
        current_node = self.start_node
        print(f"CompiledWorkflow current_node: {current_node}")
        while current_node != "__end__":
            if current_node not in self.nodes:
                raise ValueError(f"Node {current_node} not found in workflow")
                
            node_func = self.nodes[current_node]
            command = node_func(state)
            
            if hasattr(command, 'update') and command.update:
                for key, value in command.update.items():
                    print(f"update {key} to {value}")
                    state[key] = value
            
            current_node = command.goto
            
        return state
