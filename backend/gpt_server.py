from flask import Flask, request, jsonify
from flask_cors import CORS
import json, os, re, logging
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import requests

# Setup
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

here = os.path.dirname(__file__)
model = SentenceTransformer("all-MiniLM-L6-v2")

with open(os.path.join(here, "teams_with_embeddings.json"), "r", encoding="utf-8") as f:
    opportunities = json.load(f)


# URL lookup map

opportunities_lookup = {}

for team in opportunities["student_teams"]:
    for sub in team.get("subteams", []):
        if not isinstance(sub, dict):
            continue
        full_name = f"{team['name']} – {sub.get('name', 'Subteam')}"
        opportunities_lookup[full_name] = {"url": team.get("url", "")}


 
# Scoring
 

def compute_score(subteam, job_embedding, job_text):
    try:
        sub_emb = np.array(subteam["embedding"]).reshape(1, -1)
        sim = cosine_similarity(job_embedding, sub_emb)[0][0]
    except Exception:
        sim = 0.0

    tags = set(map(str.lower, subteam.get("tags", [])))

    bonus = 0
    for t in tags:
        if t in job_text:
            bonus += 0.02

    return sim + bonus



# Courses filter
 

def filter_courses(job_desc, all_courses):
    jd_lower = job_desc.lower()

    is_ai = any(k in jd_lower for k in ["artificial intelligence", "ai", "machine learning", "ml", "deep learning"])
    is_python = "python" in jd_lower

    return [
        c for c in all_courses if
        ("ai" in c.get("tags", []) and is_ai) or
        ("python" in c.get("tags", []) and is_python)
    ]


 
# JSON extraction
 

def extract_json(content: str) -> dict:
    content = content.strip().replace("```json", "").replace("```", "")

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            return json.loads(match.group(0))
        raise ValueError("No valid JSON found")


 
# LLM reasoning
 

def get_reasons_from_llm(job_desc, teams, hackathons, courses):
    def fmt(items):
        lines = []
        for x in items:
            meta = []
            if "tags" in x:
                meta.extend(x["tags"])
            if "focus" in x:
                meta.append(x["focus"])

            meta_str = " | ".join(meta[:5])

            lines.append(f"- {x['name']} ({meta_str})")

        return "\n".join(lines)


    prompt = f"""
Based on this job description:

{job_desc}

Explain briefly why each item is relevant.

Student Teams:
{fmt(teams)}

Hackathons:
{fmt(hackathons)}

Courses:
{fmt(courses)}

Respond ONLY with valid JSON.

Use the exact names provided.

Format strictly as:

{{
  "student_teams": {{
    "TEAM NAME HERE": "One sentence reason"
  }},
  "hackathons": {{
    "HACKATHON NAME HERE": "One sentence reason"
  }},
  "courses": {{
    "COURSE NAME HERE": "One sentence reason"
  }}
}}

Do not return arrays.
Every name listed MUST appear as a key in the JSON.
If you skip any item the response is invalid.
Return a reason for every entry even if brief.


"""


    res = requests.post(
        "http://127.0.0.1:1234/v1/chat/completions",
        headers={"Content-Type": "application/json"},
        json={
            "model": "wizardlm-2-7b",
            "messages": [
                {"role": "system", "content": "You explain why each opportunity is relevant."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 2048
        },
        timeout=30
    )

    res.raise_for_status()
    raw = res.json()["choices"][0]["message"]["content"]
    return extract_json(raw)


 
# Main route
 

@app.route("/generate", methods=["POST"])
def generate():
    jd = request.get_json(force=True).get("prompt", "").strip()

    if not jd:
        return jsonify({"error": "No job description provided"}), 400

    job_vec = model.encode(jd).reshape(1, -1)


    SKILL_KEYWORDS = {
        "integration", "design", "testing", "manufacturing",
        "process", "quality", "planning", "structures",
        "electrical", "mechanical", "project", "management"
    }

    TOOL_KEYWORDS = {"python", "cad", "ros", "c++", "solidworks", "catia", "fusion360"}


    jd_lower = jd.lower()


    top_teams = []

    for team in opportunities["student_teams"]:
        scored = [
            (
                compute_score(st, job_vec, jd_lower),
                st
            )
            for st in team.get("subteams", [])
            if isinstance(st, dict) and "embedding" in st
        ]

        if scored:
            scored.sort(reverse=True)
            top_teams.append((
                scored[0][0],
                {
                    "name": team["name"],
                    "url": team.get("url", ""),
                    "subteams": [st for _, st in scored[:2]]
                }
            ))

    top_teams.sort(reverse=True)
    top_teams = [t for _, t in top_teams[:3]]

    hackathons = opportunities["hackathons"][:3]
    courses = filter_courses(jd, opportunities["courses"])

    team_items = [{
        "name": f"{team['name']} – {sub.get('name', 'Subteam')}",
        "url": team.get("url", ""),
        "tags": sub.get("tags", []),
        "focus": sub.get("focus", "")
    } for team in top_teams for sub in team.get("subteams", [])]

    hackathon_items = [{"name": h["name"], "url": h.get("url", "")} for h in hackathons]
    course_items = [{"name": c["name"], "url": c.get("url", "")} for c in courses]

    try:
        reasons = get_reasons_from_llm(jd, team_items, hackathon_items, course_items)
    except Exception as e:
        logging.error(e)
        return jsonify({"error": "LLM failure"}), 500

    def with_reasons(items, reason_data):
        out = []

        for idx, x in enumerate(items):
            name = x["name"]

            reason = None

            if isinstance(reason_data, dict):
                reason = reason_data.get(name)

            elif isinstance(reason_data, list):
                if idx < len(reason_data):
                    reason = reason_data[idx]

            if not reason:
                raise ValueError(f"LLM missing reason for: {name}")

            out.append({
                "name": name,
                "reason": reason,
                "url": x.get("url") or opportunities_lookup.get(name, {}).get("url", "")
            })


        return out


    return jsonify({
        "student_teams": with_reasons(team_items, reasons.get("student_teams", [])),
        "hackathons": with_reasons(hackathon_items, reasons.get("hackathons", [])),
        "courses": with_reasons(course_items, reasons.get("courses", []))
    })


if __name__ == "__main__":
    app.run(debug=True, port=3000)
