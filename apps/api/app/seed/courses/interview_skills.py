from app.seed.helpers import L, descriptive, mcq, multi, speaking, steps

EXAM = {
    "slug": "job-interview-readiness",
    "name": "Job Interview Readiness",
    "body": "EduVerse skill track",
    "domain": "career",
    "pattern": {
        "rounds": ["HR screening", "Technical or functional", "Managerial", "HR final"],
        "assessment": "Mock interview answers scored on structure, evidence, relevance and delivery",
        "marks_per_question": 1,
        "negative_marks": 0,
        "minutes_per_question": 1.5,
        "default_section": "Interview fundamentals",
    },
}

COURSE = {
    "slug": "job-interview-skills",
    "title": "Job Interview Skills",
    "description": "Prepare for campus and lateral job interviews: a confident self-introduction, STAR stories for behavioural questions, honest strengths and weaknesses, company research, questions to ask, and delivery in person or online, with AI-scored mock answers.",
    "domain": "career",
    "level": "freshers to 3 years experience",
    "locales": ["en", "te"],
    "color": "teal",
    "exam": EXAM,
    "tree": [
        (
            "Interview Foundations",
            [
                ("Opening strong", [("First impressions", ["english-self-introduction", "interview-delivery"])]),
                ("Behavioural answers", [("Stories and self-awareness", ["interview-star-method", "interview-strengths-weaknesses"])]),
            ],
        ),
        (
            "Winning the Role",
            [("Fit and motivation", [("Research and closing", ["interview-company-research", "interview-questions-to-ask"])])],
        ),
    ],
}

CONCEPTS = {
    "interview-delivery": {
        "title": "Body language and delivery",
        "summary": "How you say it matters: steady eye contact, open posture, a calm pace, short pauses instead of fillers, and, online, a clear camera angle, good light and a quiet room.",
        "weight": 1.0,
        "prereqs": [],
        "lessons": {
            (1, "en"): L(
                "Delivery is the non-verbal part of an answer: eye contact, posture, voice, pace and, in video interviews, your setup.",
                "Interviewers judge confidence within the first minute. Sit upright and lean slightly forward, keep your hands visible and relaxed, and look at the interviewer (on video, look at the camera, not the screen). Speak a little slower than usual and pause for a second instead of saying 'umm' or 'basically'. Smile when you greet and when you close. For online interviews, test your internet, microphone and camera beforehand, sit facing a light source, keep a plain background, mute notifications, and join five minutes early.",
                [
                    ("Pause, don't fill", "Instead of 'Umm, basically, actually I...', take a breath and say 'In my final-year project, I...'."),
                    ("Video setup", "Laptop on a stack of books so the camera is at eye level, window in front of you, phone on silent."),
                ],
                [
                    "Eye contact (camera on video)",
                    "Upright, open posture",
                    "Slow down; pause instead of fillers",
                    "Test tech and join early for online interviews",
                ],
                [
                    "Looking at your own video tile instead of the camera.",
                    "Reading answers from notes on the screen.",
                    "Crossing arms or fidgeting with a pen.",
                ],
                "'SPEC': Smile, Posture, Eye contact, Calm pace.",
                "Delivery affects every round; a weak first impression makes strong answers sound weaker.",
                [("On a video call, where should you look while speaking?", "At the camera"), ("What should replace filler words?", "A short pause")],
            ),
            (1, "te"): L(
                "Delivery అంటే సమాధానంలోని మాటలు కాని భాగం: కళ్ళలోకి చూడటం (eye contact), కూర్చునే తీరు, గొంతు, వేగం, ఆన్‌లైన్ అయితే మీ సెటప్.",
                "మొదటి నిమిషంలోనే ఇంటర్వ్యూయర్ మీ ఆత్మవిశ్వాసాన్ని అంచనా వేస్తారు. నిటారుగా కూర్చోండి, చేతులు ప్రశాంతంగా ఉంచండి, ఇంటర్వ్యూయర్ వైపు చూడండి (వీడియోలో అయితే స్క్రీన్ కాదు, కెమెరా వైపు). కొంచెం నెమ్మదిగా మాట్లాడండి; 'umm', 'basically' బదులు ఒక్క క్షణం ఆగండి. ఆన్‌లైన్ ఇంటర్వ్యూకు ముందే ఇంటర్నెట్, మైక్, కెమెరా పరీక్షించండి, వెలుతురు ముఖం మీద పడేలా కూర్చోండి, ఐదు నిమిషాలు ముందే జాయిన్ అవ్వండి.",
                [("వీడియో సెటప్", "కెమెరా కంటి ఎత్తులో ఉండేలా ల్యాప్‌టాప్‌ను పుస్తకాలపై పెట్టండి, ఫోన్ సైలెంట్‌లో ఉంచండి.")],
                ["కెమెరా వైపు చూడండి", "నిటారుగా కూర్చోండి", "filler పదాల బదులు చిన్న విరామం", "ముందుగానే టెక్ పరీక్షించండి"],
                ["మీ వీడియో టైల్ వైపు చూడటం.", "స్క్రీన్ మీద నోట్స్ చదవడం."],
                "'SPEC': Smile, Posture, Eye contact, Calm pace.",
                "Delivery ప్రతి రౌండ్‌ను ప్రభావితం చేస్తుంది.",
                [("వీడియో కాల్‌లో మాట్లాడేటప్పుడు ఎక్కడ చూడాలి?", "కెమెరా వైపు")],
            ),
        },
        "flashcards": [
            ("Where to look on a video interview", "At the camera"),
            ("Replace filler words with", "A short pause"),
            ("SPEC", "Smile, Posture, Eye contact, Calm pace"),
        ],
        "questions": [
            mcq(
                "During a video interview, the best way to make 'eye contact' is to:",
                ["Look at the interviewer's face on your screen", "Look at the camera while speaking", "Look at your notes", "Keep your camera off"],
                "b",
                "Looking into the camera makes you appear to look at the interviewer; looking at the screen makes your eyes look down.",
                steps(
                    "Where is the interviewer's 'view' of you coming from?",
                    "On video, the camera is the interviewer's eyes.",
                    "Pick the option that aims your eyes at the lens.",
                    "Look at the camera while speaking.",
                    "",
                    "Watching the interviewer's video tile, which looks like you are looking away.",
                ),
                "easy",
            ),
            multi(
                "Which of these improve an online interview? (Select all that apply)",
                [
                    "Testing the microphone and camera beforehand",
                    "Sitting facing a window or light",
                    "Keeping notification sounds on",
                    "Joining a few minutes early",
                ],
                ["a", "b", "d"],
                "Testing tech, good front lighting and joining early all help; notification sounds distract you and the interviewer.",
                steps(
                    "Which choices remove distractions or technical risk?",
                    "Preparation of the setup is part of delivery.",
                    "Eliminate the option that adds distraction.",
                    "a, b and d.",
                    "",
                    "Leaving notifications on.",
                ),
                "easy",
            ),
            speaking("Thank you for having me. I am excited to talk about this role.", "నన్ను ఆహ్వానించినందుకు ధన్యవాదాలు. ఈ ఉద్యోగం గురించి మాట్లాడటానికి నేను ఉత్సాహంగా ఉన్నాను."),
        ],
    },
    "interview-star-method": {
        "title": "STAR method for behavioural questions",
        "summary": "Answer 'Tell me about a time...' questions with a STAR story: Situation, Task, Action (what you did) and Result (preferably measurable), plus what you learned.",
        "weight": 2.0,
        "prereqs": [],
        "lessons": {
            (1, "en"): L(
                "The STAR method structures a behavioural answer as Situation, Task, Action and Result.",
                "Behavioural questions ('Tell me about a time you handled a conflict / failed / led a team') test what you actually did in the past, because past behaviour predicts future behaviour. Situation: one or two sentences of context. Task: what you were responsible for. Action: the specific steps YOU took; this is the longest part, so say 'I', not just 'we'. Result: the outcome, with a number if possible (time saved, marks improved, users reached), and one line on what you learned. Prepare five or six stories from projects, internships, college events or part-time work, and reuse them for different questions.",
                [
                    (
                        "Conflict in a project team",
                        "S: In our final-year project, two teammates disagreed on the database design and work stopped. T: As team lead I had to get us moving before the review in a week. A: I met each of them, listed the pros and cons of both designs, and we tested both on sample data. R: We chose the faster design, finished two days early and scored 9/10 in the review. I learned to settle debates with data, not opinions.",
                    ),
                ],
                [
                    "S: brief context",
                    "T: your responsibility",
                    "A: your specific actions (longest part)",
                    "R: measurable outcome + learning",
                    "Prepare 5-6 reusable stories",
                ],
                ["Spending most of the time on the situation.", "Saying only 'we' so the interviewer can't tell what you did.", "Ending without a result."],
                "STAR: Set the scene, Target, Act, Reap the result.",
                "Most HR and managerial rounds include 2-3 behavioural questions; STAR is the standard way interviewers score them.",
                [("Which STAR part should be longest?", "Action"), ("What makes a Result strong?", "A measurable outcome and a learning")],
            ),
        },
        "flashcards": [
            ("STAR stands for", "Situation, Task, Action, Result"),
            ("Longest part of a STAR answer", "Action"),
            ("How many stories to prepare", "Five or six reusable ones"),
        ],
        "questions": [
            mcq(
                "In a STAR answer, which part should take the most time?",
                ["Situation", "Task", "Action", "Result"],
                "c",
                "The Action shows what you personally did, which is what the interviewer is assessing.",
                steps(
                    "What is the interviewer really trying to learn?",
                    "Behavioural questions assess your own behaviour.",
                    "Find the part that describes what you did.",
                    "Action.",
                    "",
                    "Spending too long describing the situation.",
                ),
                "easy",
            ),
            mcq(
                "Which is the strongest 'Result' line for a STAR story about improving a college fest's registrations?",
                [
                    "It went well and everyone was happy.",
                    "Registrations rose from 300 to 520, and I learned that reminders on WhatsApp work better than posters.",
                    "We worked very hard as a team.",
                    "The fest happened on time.",
                ],
                "b",
                "A strong result is specific and measurable and ends with a learning.",
                steps(
                    "Which option has a number?",
                    "Results should be measurable and reflective.",
                    "Look for evidence plus a learning.",
                    "Option (b).",
                    "",
                    "Choosing a vague positive statement.",
                ),
                "easy",
            ),
            descriptive(
                "Interview: Tell me about a time you faced a difficult problem in a team and how you handled it.",
                [
                    ("Situation and task", 2, ["describes the situation and context briefly", "states the task or your responsibility"]),
                    ("Action", 4, ["explains the specific actions you took personally", "shows communication or problem solving with the team"]),
                    ("Result", 3, ["gives a clear result or outcome with a number", "states what you learned"]),
                    ("Delivery", 1, ["concise and structured answer"]),
                ],
                "In my final-year project (situation), two teammates disagreed on the database design and work stopped a week before our review. As team lead, my task was to get us moving again. I met each of them separately, listed the pros and cons of both designs, and suggested we test both on sample data that evening. The test showed one design was twice as fast, so we chose it together. We finished two days early and scored 9 out of 10 in the review. I learned to settle disagreements with data and to talk to people one to one before a group discussion.",
                qtype="interview",
                word_limit=180,
            ),
            speaking(
                "As team lead, I tested both options with real data, and we finished two days early.",
                "టీమ్ లీడ్‌గా నేను రెండు ఆప్షన్‌లను నిజమైన డేటాతో పరీక్షించాను, మేము రెండు రోజులు ముందే పూర్తి చేశాం.",
            ),
        ],
    },
    "interview-strengths-weaknesses": {
        "title": "Strengths and weaknesses",
        "summary": "Name strengths that matter for the role and prove each with a short example; name a real but non-critical weakness and the concrete steps you are taking to improve it.",
        "weight": 1.5,
        "prereqs": ["interview-star-method"],
        "lessons": {
            (1, "en"): L(
                "Strength and weakness questions test self-awareness: can you judge yourself honestly and keep improving?",
                "Strengths: pick two or three relevant to the job (for a developer: problem solving, learning new tools quickly; for sales: persistence, listening) and back each with evidence from a mini STAR story. Weakness: choose a real one that is not central to the role, show you are aware of it, and describe what you are doing about it. Avoid clichés like 'I am a perfectionist' or 'I work too hard', which sound rehearsed, and never claim to have no weaknesses.",
                [
                    (
                        "Strength with proof",
                        "'I learn new tools quickly: I picked up React in three weeks during my internship and shipped the attendance dashboard.'",
                    ),
                    (
                        "Weakness with a plan",
                        "'I used to hesitate to speak in large meetings. I joined our college debate club and now present our weekly project update.'",
                    ),
                ],
                [
                    "Strengths: relevant + evidence",
                    "Weakness: real, non-critical, with an improvement plan",
                    "Avoid clichés",
                    "Never say 'I have no weaknesses'",
                ],
                ["'My weakness is that I am a perfectionist.'", "Choosing a weakness that is the core skill of the job.", "Listing strengths without proof."],
                "Strength = Claim + Proof. Weakness = Honest + Action.",
                "'What are your strengths and weaknesses?' appears in nearly every HR round.",
                [
                    ("What should follow each strength you name?", "An example that proves it"),
                    ("What must a weakness answer include?", "The steps you are taking to improve"),
                ],
            ),
        },
        "flashcards": [("Strength answer formula", "Claim + proof (example)"), ("Weakness answer formula", "Real, non-critical weakness + improvement steps")],
        "questions": [
            mcq(
                "Which is the best answer to 'What is your greatest weakness?' for a junior data analyst role?",
                [
                    "I don't have any weaknesses.",
                    "I am a perfectionist and work too hard.",
                    "I used to struggle with presenting to large groups, so I volunteer to present our team's weekly report and have improved a lot.",
                    "I am not good with numbers or Excel.",
                ],
                "c",
                "Option (c) is honest, not central to the analyst role, and shows concrete improvement.",
                steps(
                    "What is the interviewer testing with this question?",
                    "Self-awareness and growth.",
                    "Remove clichés, denials and weaknesses that are core job skills.",
                    "Option (c).",
                    "",
                    "Choosing (d), a weakness in the core skill of the role.",
                ),
                "medium",
            ),
            descriptive(
                "Interview: What are your strengths? Give at least two, with examples.",
                [
                    ("Relevant strengths", 3, ["names a clear strength relevant to the job", "names a second strength"]),
                    ("Evidence", 5, ["gives a specific example that proves the strength", "includes a result or number"]),
                    ("Link to role", 2, ["connects the strengths to the role"]),
                ],
                "My first strength is problem solving: in my internship I found why our report took ten minutes to load and cut it to under one minute by adding an index. My second strength is learning quickly: I learned React in three weeks and built the team's attendance dashboard. Both matter for this developer role, where I will often debug unfamiliar code and pick up new tools.",
                qtype="interview",
                word_limit=150,
            ),
        ],
    },
    "interview-company-research": {
        "title": "Company research and 'Why should we hire you?'",
        "summary": "Research the company's products, customers, recent news and the role's requirements, then answer 'Why this company?' and 'Why should we hire you?' by matching your evidence to their needs.",
        "weight": 1.5,
        "prereqs": [],
        "lessons": {
            (1, "en"): L(
                "Company research means learning what the employer does and needs, so your answers connect your skills to their goals.",
                "Before the interview, read the company website (products, customers, mission), recent news, the job description line by line, and employee posts on LinkedIn. Note three requirements of the role and one story that proves each. 'Why do you want to join us?': mention something specific about the company (a product, a value, a recent project) and how it fits your goals. 'Why should we hire you?': summarise in three points how your skills and evidence match their top requirements, and add your enthusiasm to learn.",
                [
                    (
                        "Matching answer",
                        "'Your job description asks for SQL, clear communication and ownership. I wrote SQL reports daily in my internship, presented findings to the sales head every week, and took ownership of automating our attendance sheet.'",
                    ),
                ],
                [
                    "Read website, news and the job description",
                    "Map three role requirements to three stories",
                    "'Why us?': be specific about the company",
                    "'Why you?': match evidence to their needs",
                ],
                [
                    "Generic answers like 'It is a good company with good growth'.",
                    "Talking only about salary or location.",
                    "Not knowing what the company sells.",
                ],
                "Their needs → your proof → your enthusiasm.",
                "'Why should we hire you?' is a common closing question in HR rounds.",
                [("Where do you find the role's key requirements?", "In the job description")],
            ),
        },
        "flashcards": [
            ("Three sources for company research", "Website, recent news, job description (plus employee profiles)"),
            ("Formula for 'Why should we hire you?'", "Their needs → your proof → your enthusiasm"),
        ],
        "questions": [
            mcq(
                "Which answer to 'Why do you want to join our company?' is strongest?",
                [
                    "It is a big company and the salary is good.",
                    "My friends work here.",
                    "Your UPI payments product serves small shop owners, and I want to build tools for first-time digital users like my parents' shop.",
                    "I applied to many companies and you replied first.",
                ],
                "c",
                "It is specific to the company and links its work to the candidate's motivation.",
                steps(
                    "Which option could only be said about this company?",
                    "Specific research shows genuine interest.",
                    "Remove the generic or self-centred answers.",
                    "Option (c).",
                    "",
                    "Leading with salary or convenience.",
                ),
                "easy",
            ),
            descriptive(
                "Interview: Why should we hire you?",
                [
                    (
                        "Match to requirements",
                        4,
                        ["matches your skills to the requirements of the role", "refers to something specific about the company or job"],
                    ),
                    ("Evidence", 4, ["gives evidence or examples for the skills you claim"]),
                    ("Enthusiasm and close", 2, ["shows enthusiasm and willingness to learn"]),
                ],
                "Your job description asks for SQL, clear communication and ownership. In my internship I wrote SQL reports every day, and I presented weekly findings to the sales head, which improved my communication. I also took ownership of automating our attendance sheet, which saved the office two hours a week. I am excited about how your company builds payment tools for small businesses, and I am eager to keep learning in this role.",
                qtype="interview",
                word_limit=150,
            ),
        ],
    },
    "interview-questions-to-ask": {
        "title": "Questions to ask and closing the interview",
        "summary": "End by asking two or three thoughtful questions about the role, team, success measures or learning, then thank the interviewer and restate your interest; send a short thank-you message the same day.",
        "weight": 1.0,
        "prereqs": ["interview-company-research"],
        "lessons": {
            (1, "en"): L(
                "When the interviewer asks 'Do you have any questions for us?', asking good questions shows interest and helps you judge the job.",
                "Prepare three questions and ask two: about the work ('What would a typical week look like?'), success ('What would you expect me to achieve in the first three months?'), the team ('How is the team structured?'), or learning ('How do new joiners get trained?'). Avoid questions answered on the website, and leave salary and leave policy for the HR or offer stage unless they raise it. Close by thanking them, restating your interest in one line, and asking about next steps. Send a short thank-you email or message the same day.",
                [
                    (
                        "Closing line",
                        "'Thank you for your time. After this conversation I'm even more interested in the role. What are the next steps in the process?'",
                    )
                ],
                [
                    "Always have 2-3 questions ready",
                    "Ask about work, success, team or learning",
                    "Close: thanks + interest + next steps",
                    "Send a thank-you note the same day",
                ],
                [
                    "Saying 'No questions'.",
                    "Asking only about salary and holidays in the first round.",
                    "Asking something clearly answered on the company website.",
                ],
                "Ask about Work, Win (success), Team, Training.",
                "The closing minutes shape the interviewer's final impression.",
                [("What should you do after the interview the same day?", "Send a short thank-you message")],
            ),
        },
        "flashcards": [
            ("Answer to 'Any questions for us?'", "Never 'no'; ask 2-3 prepared questions"),
            ("Closing formula", "Thanks + restate interest + ask next steps"),
        ],
        "questions": [
            mcq(
                "In a first-round interview, which is the best question to ask the interviewer?",
                [
                    "How many leaves do I get?",
                    "What would you expect me to achieve in my first three months?",
                    "What does your company do?",
                    "No, I don't have any questions.",
                ],
                "b",
                "It shows you are thinking about doing well in the role; the others are premature, already researchable, or show no interest.",
                steps(
                    "Which question shows interest in the work itself?",
                    "Good questions focus on the work, success, team or learning.",
                    "Remove questions about perks, basic facts or no question at all.",
                    "Option (b).",
                    "",
                    "Leading with leave or salary questions in the first round.",
                ),
                "easy",
            ),
            speaking(
                "Thank you for your time. What are the next steps in the process?",
                "మీ సమయానికి ధన్యవాదాలు. ఈ ప్రక్రియలో తదుపరి దశలు ఏమిటి?",
            ),
        ],
    },
}
