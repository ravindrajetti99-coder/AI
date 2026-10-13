from conftest import API, make_actor


def test_domains_and_course_list(sclient):
    domains = {d["code"]: d["course_count"] for d in sclient.get(f"{API}/domains").json()}
    assert domains == {"competitive": 1, "professional": 1, "academic": 1, "language": 1, "technology": 1, "career": 1}
    courses = sclient.get(f"{API}/courses").json()
    assert len(courses) == 6 and all(c["concept_count"] > 0 and c["question_count"] > 0 for c in courses)
    assert [c["slug"] for c in sclient.get(f"{API}/courses", params={"domain": "technology"}).json()] == ["python-fundamentals"]
    assert [c["slug"] for c in sclient.get(f"{API}/courses", params={"q": "physics"}).json()] == ["class10-physics-electricity"]


def test_course_detail_tree(sclient):
    r = sclient.get(f"{API}/courses/ssc-cgl-quant-arithmetic")
    assert r.status_code == 200
    course = r.json()
    assert course["exam_profile"]["pattern"]["negative_marks"] == 0.5
    module = course["tree"][0]
    assert module["node_type"] == "module" and module["title"] == "Arithmetic"
    assert [c["node_type"] for c in module["children"]] == ["chapter"] * 3
    topic = module["children"][0]["children"][0]
    assert topic["node_type"] == "topic"
    assert [c["slug"] for c in topic["concepts"]] == ["percentage-basics", "percentage-change", "successive-percentage"]
    assert course["concept_count"] == 7
    by_id = sclient.get(f"{API}/courses/{course['id']}")
    assert by_id.status_code == 200 and by_id.json()["slug"] == course["slug"]
    assert sclient.get(f"{API}/courses/nope").status_code == 404


def test_concept_detail_graph_and_shared_concepts(sclient):
    c = sclient.get(f"{API}/concepts/compound-interest").json()
    assert {p["slug"] for p in c["prerequisites"]} == {"simple-interest", "successive-percentage"}
    assert c["lesson_levels"] == {"en": [1, 2]}
    assert c["flashcard_count"] == 3 and c["question_count"] > 5
    basics = sclient.get(f"{API}/concepts/percentage-basics").json()
    assert {u["slug"] for u in basics["unlocks"]} == {"percentage-change", "simple-interest"}
    assert basics["lesson_levels"] == {"en": [1, 2], "te": [1]}
    shared = sclient.get(f"{API}/concepts/english-self-introduction").json()
    assert {x["slug"] for x in shared["courses"]} == {"spoken-english-telugu", "job-interview-skills"}


def test_admin_builds_a_course(sclient):
    admin = make_actor(sclient, "admin")
    learner = make_actor(sclient, "learner")
    body = {"slug": "upsc-polity", "title": "UPSC Polity", "domain": "competitive", "exam_profile_slug": "ssc-cgl-tier1"}
    assert learner.post(f"{API}/admin/courses", json=body).status_code == 403
    course = admin.post(f"{API}/admin/courses", json=body)
    assert course.status_code == 201
    assert admin.post(f"{API}/admin/courses", json=body).status_code == 409
    cid = course.json()["id"]
    module = admin.post(f"{API}/admin/courses/{cid}/nodes", json={"node_type": "module", "title": "Constitution"}).json()
    chapter = admin.post(f"{API}/admin/courses/{cid}/nodes", json={"node_type": "chapter", "title": "Preamble", "parent_id": module["id"]}).json()
    concept = admin.post(
        f"{API}/admin/concepts",
        json={"slug": "preamble", "title": "The Preamble", "domain": "competitive", "node_id": chapter["id"], "prerequisite_slugs": ["percentage-basics"]},
    )
    assert concept.status_code == 201
    missing = admin.post(f"{API}/admin/concepts", json={"slug": "fundamental-rights", "title": "FR", "domain": "competitive", "prerequisite_slugs": ["nope"]})
    assert missing.status_code == 404
    tree = sclient.get(f"{API}/courses/upsc-polity").json()["tree"]
    assert tree[0]["children"][0]["concepts"][0]["slug"] == "preamble"
    assert sclient.get(f"{API}/concepts/preamble").json()["prerequisites"][0]["slug"] == "percentage-basics"
