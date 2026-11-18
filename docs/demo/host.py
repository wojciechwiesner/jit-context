"""Run Hermes' native agent loop with its plugin lifecycle in an isolated process."""

import json
import os
from pathlib import Path
import sys


def main():
    from hermes_cli import plugins
    from hermes_state import SessionDB
    from run_agent import AIAgent

    plugins.discover_plugins()
    prompt = json.loads(sys.stdin.read())
    db = SessionDB(Path(os.environ['HERMES_HOME']) / 'state.db')
    session = 'bench_receipt_import'
    db.create_session(session, 'cli', cwd=os.getcwd())
    tools = ['file', 'terminal'] if sys.argv[2] == 'tools' else []
    agent = AIAgent(provider='custom', api_mode='chat_completions', api_key='demo-proxy',
                    base_url=os.environ['OPENAI_BASE_URL'], model=sys.argv[1],
                    enabled_toolsets=tools, max_iterations=7 if tools else 1,
                    quiet_mode=True, platform='cli', cwd=os.getcwd(), session_id=session,
                    session_db=db, skip_memory=True, skip_background_review=True,
                    run_budget_seconds=355)
    # The gateway adapts the provider's complete result to streaming when requested.
    try:
        result = agent.run_conversation(prompt)
        print(json.dumps({'type': 'result', 'text': result.get('final_response', ''),
                          'failed': bool(result.get('failed')), 'error': result.get('error'),
                          'engine_api_calls': getattr(agent, '_api_call_count', None)}), flush=True)
    finally:
        agent.close()
        db.close()


if __name__ == '__main__':
    main()
