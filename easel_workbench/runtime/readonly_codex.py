"""Shared ephemeral, tool-disabled Codex CLI contract for content collection.

Callers own their input, schema, bounded subprocess and temporary directory.
This module only constructs arguments; it does not inspect login state, read
credentials, load personal documents, launch a process or resume a conversation.
"""
import pathlib

CODEX=pathlib.Path('C:/Users/38482/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe')
DISABLED=('shell_tool','unified_exec','apps','plugins','hooks','browser_use','browser_use_external','computer_use','image_generation','multi_agent','code_mode_host','skill_search','memories')

def command(directory):
    result=[str(CODEX),'exec','--ignore-user-config','--ephemeral','--sandbox','read-only','--skip-git-repo-check','--cd',str(directory),'--output-schema',str(directory/'schema.json'),'--output-last-message',str(directory/'answer.json'),'--color','never']
    for feature in DISABLED:result.extend(['--disable',feature])
    return result+['-']
