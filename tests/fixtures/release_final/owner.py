"""Trusted bundled test owner records actual host callbacks beside its package."""
import atexit
import json
import os
from pathlib import Path


def register(host):
    @atexit.register
    def exited():
        with Path("owner-stops.txt").open("a", encoding="utf-8") as output:
            output.write(str(os.getpid()) + "\n")
    def invoked(payload, context):
        with Path("owner-results.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(dict(action=context.component_id, parameter=context.action_parameter,
                                         operation=context.operation, diff=context.adjustment_diff,
                                         request=context.command_id, pid=os.getpid())) + "\n")
        return {"ok": True}
    host.register_handler("handler.main", "invoke", invoked)
