from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.supervisor import IntentDecision, ResolvedContext, TaskPlan
from app.schemas.vishue_state import DurableVishueState, VishueState


@dataclass(frozen=True)
class SupervisorRuntime:
    request: ChatRequest
    context: ResolvedContext
    plan: Callable[[ResolvedContext, IntentDecision], TaskPlan]
    execute: Callable[[ChatRequest, IntentDecision, TaskPlan], Awaitable[ChatResponse]]


def plan_turn(state: VishueState, runtime: Runtime[SupervisorRuntime]) -> dict[str, TaskPlan]:
    context = runtime.context
    return {"plan": context.plan(context.context, state["decision"])}


async def execute_turn(
    state: VishueState, runtime: Runtime[SupervisorRuntime]
) -> dict[str, ChatResponse]:
    context = runtime.context
    result = await context.execute(context.request, state["decision"], state["plan"])
    return {"response": result}


product_supervisor = (
    StateGraph(VishueState, context_schema=SupervisorRuntime)
    .add_node("plan_turn", plan_turn)
    .add_node("execute_turn", execute_turn)
    .add_edge(START, "plan_turn")
    .add_edge("plan_turn", "execute_turn")
    .add_edge("execute_turn", END)
    .compile()
)


@dataclass
class DurableRuntime:
    supervisor: SupervisorRuntime
    decision: IntentDecision
    plan: TaskPlan | None = None
    response: ChatResponse | None = None


def plan_durable(state: DurableVishueState, runtime: Runtime[DurableRuntime]) -> dict:
    context = runtime.context
    context.plan = context.supervisor.plan(context.supervisor.context, context.decision)
    return {"execution_status": "planned"}


async def execute_durable(state: DurableVishueState, runtime: Runtime[DurableRuntime]) -> dict:
    context = runtime.context
    if context.plan is None:
        raise ValueError("Missing turn plan")
    context.response = await context.supervisor.execute(
        context.supervisor.request, context.decision, context.plan
    )
    return {"execution_status": "done"}


def durable_supervisor(checkpointer):
    return (
        StateGraph(DurableVishueState, context_schema=DurableRuntime)
        .add_node("plan_turn", plan_durable)
        .add_node("execute_turn", execute_durable)
        .add_edge(START, "plan_turn")
        .add_edge("plan_turn", "execute_turn")
        .add_edge("execute_turn", END)
        .compile(checkpointer=checkpointer)
    )
