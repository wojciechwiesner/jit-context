"""
JIT Context Query Tool for Agent Zero.
Allows querying L0 hot facts, adding dynamic memory facts, and checking epistemic status.
"""

import json
from helpers.tool import Tool, Response
from usr.plugins.jit_context.helpers.runtime import JITContextRuntime
from usr.plugins.jit_context.helpers.invariants import InvariantChecker


class JITContextQuery(Tool):
    async def execute(
        self,
        action: str = "get_facts",
        key: str = "",
        value: str = "",
        project_scope: str = "",
        **kwargs
    ):
        runtime = JITContextRuntime()
        
        if action == "get_facts":
            facts = runtime.get_hot_facts()
            res = {
                "active_scope": runtime.active_scope,
                "circuit_breaker": runtime.circuit_breaker.state,
                "hot_facts_count": len(facts),
                "facts": facts
            }
            return Response(message=json.dumps(res, indent=2), break_loop=False)
            
        elif action == "set_fact":
            if not key or not value:
                return Response(message="Error: 'key' and 'value' are required for set_fact.", break_loop=False)
            runtime.set_hot_fact(key, value, epistemic_weight=1.0)
            return Response(message=f"Successfully stored hot fact '{key}'.", break_loop=False)
            
        elif action == "set_scope":
            if not project_scope:
                return Response(message="Error: 'project_scope' is required for set_scope.", break_loop=False)
            # Apply twice to pass hysteresis guard immediately if manual
            runtime.update_project_scope(project_scope)
            runtime.update_project_scope(project_scope)
            return Response(message=f"Active project scope set to '{runtime.active_scope}'.", break_loop=False)
            
        elif action == "compile_preview":
            capsule = runtime.compile_capsule(agent=self.agent)
            return Response(message=capsule if capsule else "(Empty capsule - mode disabled)", break_loop=False)
            
        else:
            return Response(
                message=f"Unknown action '{action}'. Available actions: get_facts, set_fact, set_scope, compile_preview.",
                break_loop=False
            )
