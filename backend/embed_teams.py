from sentence_transformers import SentenceTransformer
import json
import os

# Load data
here = os.path.dirname(__file__)
with open(os.path.join(here, "opportunities.json"), "r", encoding="utf-8") as f:
    data = json.load(f)

model = SentenceTransformer("all-MiniLM-L6-v2")

# Encode student teams and subteams
teams = data.get("student_teams", [])
for team in teams:
    full_text = " ".join([
        str(team.get("name", "")),
        str(team.get("description", "")),
        " ".join(team.get("tags", [])) if isinstance(team.get("tags"), list) else ""
    ])

    team["embedding"] = model.encode(full_text).tolist()

    subteams = team.get("subteams", [])
    if isinstance(subteams, list):
        for sub in subteams:
            if isinstance(sub, dict):
                sub_text = " ".join([
                    str(sub.get("name", "")),
                    str(sub.get("focus", "")),
                    " ".join(sub.get("tags", [])) if isinstance(sub.get("tags"), list) else ""
                ])

                sub["embedding"] = model.encode(sub_text).tolist()

# Encode hackathons
hackathons = data.get("hackathons", [])
for hack in hackathons:
    full_text = " ".join([
        str(hack.get("name", "")),
        str(hack.get("description", "")),
        " ".join(hack.get("tags", [])) if isinstance(hack.get("tags"), list) else ""
    ])

    hack["embedding"] = model.encode(full_text).tolist()

# Encode courses
courses = data.get("courses", [])
for course in courses:
    full_text = " ".join([
        str(course.get("name", "")),
        str(course.get("description", "")),
        " ".join(course.get("tags", [])) if isinstance(course.get("tags"), list) else ""
    ])

    course["embedding"] = model.encode(full_text).tolist()

# Save output
with open(os.path.join(here, "teams_with_embeddings.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
