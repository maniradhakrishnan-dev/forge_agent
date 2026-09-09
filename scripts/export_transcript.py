#!/usr/bin/env python3
"""
Utility script to export an Antigravity IDE conversation transcript (.jsonl)
into a readable Markdown document inside docs/conversations/.
Usage:
    python3 scripts/export_transcript.py [SESSION_ID]
"""

import sys
import os
import glob
import json
import re

BRAIN_DIR = os.path.expanduser("~/.gemini/antigravity-ide/brain")

def get_target_session_id():
    if len(sys.argv) > 1:
        return sys.argv[1]
    # Default to second most recent if current is empty or latest completed
    sessions = sorted(
        [d for d in os.listdir(BRAIN_DIR) if os.path.isdir(os.path.join(BRAIN_DIR, d)) and not d.startswith(".")],
        key=lambda d: os.path.getmtime(os.path.join(BRAIN_DIR, d)),
        reverse=True
    )
    for s in sessions:
        transcript_path = os.path.join(BRAIN_DIR, s, ".system_generated", "logs", "transcript.jsonl")
        if os.path.exists(transcript_path) and os.path.getsize(transcript_path) > 1000:
            return s
    return sessions[0] if sessions else None

def parse_user_content(text):
    if not text:
        return "", ""
    req_match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", text, re.DOTALL)
    req = req_match.group(1).strip() if req_match else text.strip()
    
    meta_match = re.search(r"<ADDITIONAL_METADATA>(.*?)</ADDITIONAL_METADATA>", text, re.DOTALL)
    meta = meta_match.group(1).strip() if meta_match else ""
    return req, meta

def export_session(session_id):
    path = os.path.join(BRAIN_DIR, session_id, ".system_generated", "logs", "transcript.jsonl")
    if not os.path.exists(path):
        print(f"Error: Transcript not found at {path}")
        return

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    dialogue = []
    current_user = None
    current_asst_parts = []
    current_tool_summaries = []

    for line in lines:
        try:
            d = json.loads(line)
            t = d.get("type")
            if t == "USER_INPUT":
                if current_user is not None:
                    dialogue.append({
                        "user": current_user,
                        "asst": "\n\n".join(current_asst_parts).strip(),
                        "tools": current_tool_summaries
                    })
                    current_asst_parts = []
                    current_tool_summaries = []
                raw_c = d.get("content", "")
                req, meta = parse_user_content(raw_c)
                current_user = {
                    "time": d.get("created_at"),
                    "text": req,
                    "meta": meta,
                    "step": d.get("step_index")
                }
            elif t == "PLANNER_RESPONSE":
                if d.get("content"):
                    current_asst_parts.append(d["content"])
                if d.get("tool_calls"):
                    for tc in d["tool_calls"]:
                        name = tc.get("name")
                        args = tc.get("args", {})
                        summary = args.get("toolSummary") or args.get("CommandLine") or name
                        current_tool_summaries.append(f"`{name}`: {summary}")
        except Exception:
            pass

    if current_user is not None:
        dialogue.append({
            "user": current_user,
            "asst": "\n\n".join(current_asst_parts).strip(),
            "tools": current_tool_summaries
        })

    os.makedirs("docs/conversations", exist_ok=True)
    out_file = f"docs/conversations/{session_id[:8]}_transcript.md"

    md_out = [
        f"# Conversation Transcript: `{session_id}`",
        f"**Source Path:** `{path}`  ",
        f"**Total Turns:** {len(dialogue)}  \n",
        "---\n"
    ]

    for i, turn in enumerate(dialogue):
        u = turn["user"]
        step = u["step"]
        time = u["time"]
        user_text = u["text"]
        md_out.append(f"## Turn {i+1} — Step {step} ({time})\n")
        md_out.append("### 👤 User\n```text\n" + user_text + "\n```\n")
        
        if "Terminal buffer content:" in u["meta"]:
            m_term = re.search(r"Terminal buffer content:(.*?)(?=</ADDITIONAL_METADATA>|$)", u["meta"], re.DOTALL)
            if m_term:
                term_snip = m_term.group(1).strip()
                md_out.append("<details><summary>📎 Terminal Output Attached</summary>\n\n```text\n" + term_snip + "\n```\n</details>\n")
        
        if turn["tools"]:
            md_out.append(f"### ⚙️ Tools Used ({len(turn['tools'])})")
            for t_item in turn["tools"][:12]:
                md_out.append(f"- {t_item}")
            if len(turn["tools"]) > 12:
                md_out.append(f"- *... and {len(turn['tools']) - 12} more tool actions*")
            md_out.append("")

        if turn["asst"]:
            md_out.append("### 🤖 Assistant\n")
            md_out.append(turn["asst"])
        
        md_out.append("\n---\n")

    with open(out_file, "w", encoding="utf-8") as f_out:
        f_out.write("\n".join(md_out))

    print(f"Successfully exported {len(dialogue)} turns to {out_file}")

if __name__ == "__main__":
    sid = get_target_session_id()
    if sid:
        print(f"Exporting session: {sid}")
        export_session(sid)
    else:
        print("No active session found.")
