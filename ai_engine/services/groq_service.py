import json
from groq import Groq
from decouple import config


class GroqAIService:
    """
    AI service powered by Groq (llama3-70b-8192 by default).
    Drop-in replacement for GeminiExtractionService.
    """

    def __init__(self):
        self.client = Groq(api_key=config('GROQ_API_KEY'))
        self.model = config('GROQ_MODEL', default='openai/gpt-oss-20b')

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _chat_json(self, prompt: str) -> dict:
        """Call Groq and parse the response as JSON."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        return json.loads(raw)

    def _chat_text(self, prompt: str, temperature: float = 0.6) -> str:
        """Call Groq and return plain text."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()

    # ------------------------------------------------------------------ #
    # Public methods
    # ------------------------------------------------------------------ #

    def process_screening(self, jd_text: str, resume_text: str) -> dict:
        """
        Extracts information from JD and Resume and calculates ATS score.
        """
        prompt = f"""
You are an expert HR Analyst and ATS (Applicant Tracking System).
Analyze the following Job Description (JD) and Candidate Resume.

--- JOB DESCRIPTION ---
{jd_text}

--- CANDIDATE RESUME ---
{resume_text}

--- TASK ---
1. Extract Job Details (Role, Department, Required Skills).
2. Extract Candidate Details (Name, Email, Skills).
3. Calculate an ATS Match Score (0-100) based on how well the resume matches the JD.
4. Provide 2-3 "Key Highlights" (strengths).

Return ONLY a valid JSON object with this structure:
{{
    "job_config": {{
        "title": "Extracted Job Title",
        "department": "Extracted Department",
        "skills": ["Skill1", "Skill2"]
    }},
    "candidate_details": {{
        "name": "Candidate Full Name",
        "email": "Candidate Email",
        "skills": ["Skill1", "Skill2"],
        "ats_score": 85,
        "highlights": ["Highlight 1", "Highlight 2"],
        "experience": [
            {{
                "role": "Job Title",
                "company": "Company Name",
                "duration": "e.g. 2 Years",
                "description": "Brief summary of achievements"
            }}
        ],
        "education": [
            {{
                "degree": "Degree Name",
                "school": "University Name",
                "year": "Graduation Year"
            }}
        ],
        "jd_match_explanation": "A short paragraph explaining how the candidate's background matches the JD.",
        "strengths": ["Strength 1", "Strength 2"],
        "concerns": ["Potential Concern 1"]
    }}
}}
"""
        try:
            print("DEBUG: Calling Groq service (process_screening)...")
            return self._chat_json(prompt)
        except Exception as e:
            print(f"Groq Error (process_screening): {e}")
            return {
                "error": str(e),
                "job_config": {"title": "Extraction Failed", "department": "N/A", "skills": []},
                "candidate_details": {
                    "name": "N/A",
                    "email": "N/A",
                    "skills": [],
                    "ats_score": 0,
                    "highlights": [f"Error: {str(e)}"],
                    "experience": [],
                    "education": [],
                    "jd_match_explanation": "Failed to generate AI screening summary.",
                    "strengths": [],
                    "concerns": []
                },
            }

    def evaluate_answer(self, question_text: str, answer_text: str) -> dict:
        """
        Evaluates a candidate's answer and returns scoring dimensions.
        """
        safe_question = question_text[:2000] if question_text else ""
        safe_answer = answer_text[:6000] if answer_text else ""

        prompt = f"""
You are a supportive, Senior-medium-strict technical interviewer. 
Your goal is to evaluate the candidate's answer fairly, being lenient on minor grammatical errors, nervousness, or slight technical hesitations. Reward effort, partial correctness, and a general understanding of the concepts rather than demanding absolute perfection.

Evaluate the candidate's answer to the following technical question.

Question: {safe_question}
Candidate's Answer: {safe_answer}

Score the answer from 0 to 100 on three dimensions, keeping your lenient, supportive baseline in mind:
1. Relevance  – does it reasonably address the core of the question?
2. Accuracy   – is the technical/factual content generally correct (allow for minor slips)?
3. Clarity    – is the explanation understandable and well-intentioned?

Also provide a single overall score (0-100) and one sentence of brief, encouraging professional feedback.

Return ONLY a JSON object with this exact structure:
{{
    "relevance_score": 85,
    "accuracy_score": 90,
    "clarity_score": 80,
    "overall_score": 85,
    "feedback": "Professional feedback here."
}}
"""
        try:
            return self._chat_json(prompt)
        except Exception as e:
            print(f"Groq Error (evaluate_answer): {e}")
            return {
                "relevance_score": 0,
                "accuracy_score": 0,
                "clarity_score": 0,
                "overall_score": 0,
                "feedback": "Could not evaluate.",
            }

    def generate_next_question(self, interview, previous_answer=None, previous_score=None) -> str:
        """
        Generates the next technical interview question dynamically.
        Varies difficulty from beginner to professional level based on performance.
        Enforces a conversational flow like two people speaking and strictly prevents duplicate questions.
        """
        jd_text = interview.job.description if interview.job else "No job description provided."
        resume_text = interview.resume_text if interview.resume_text else "No resume provided."

        # Fetch conversation history from database
        from ai_engine.models import Response
        history_responses = Response.objects.filter(interview=interview).order_by('question_index')
        history_items = []
        for r in history_responses:
            history_items.append(f"Interviewer: {r.question_text}")
            history_items.append(f"Candidate: {r.answer_text}")
        
        history_str = "\n".join(history_items)
        # Keep only the last ~6000 characters of history to avoid context window limits
        if len(history_str) > 6000:
            history_str = "...(earlier context omitted)...\n" + history_str[-6000:]

        if not history_str or history_str.strip() == "...(earlier context omitted)...\n":
            history_str = "(No conversation history yet. This is the start of the interview.)"

        # List of questions already generated to prevent duplication
        already_asked_questions = [q["text"] for q in (interview.question_bank or [])]
        already_asked_list = "\n".join([f"- {q}" for q in already_asked_questions])
        if not already_asked_list:
            already_asked_list = "(None)"

        # Difficulty logic for evaluating candidate from beginner to professional
        if previous_score is None:
            difficulty_instruction = (
                "Start with a foundational (Beginner level) technical question focusing on a key skill or project "
                "from their resume to assess basic knowledge relevant to the role."
            )
        elif previous_score > 85:
            difficulty_instruction = (
                "The candidate showed excellent proficiency. Ask a highly advanced (Professional/Architectural level) "
                "question about a complex project, design decision, or advanced skill from their resume to challenge them."
            )
        elif previous_score > 60:
            difficulty_instruction = (
                "The candidate has a good grasp. Ask a solid (Intermediate level) technical question "
                "concerning a project, tool, or achievement mentioned on their resume to explore their practical experience."
            )
        else:
            difficulty_instruction = (
                "The candidate struggled or was average. Ask a clear, direct technical question "
                "about a simpler skill or concept listed on their resume to re-verify their understanding."
            )

        prompt = f"""
You are a Senior Technical Recruiter conducting a live, voice-only, highly interactive and conversational 1-on-1 interview.
The interview must sound like a natural, friendly two-person conversation.

Job Description (JD):
{jd_text[:1200]}

Candidate's Resume:
{resume_text[:1200]}

Candidate Name:
{interview.candidate_name or "the candidate"}

Conversation History so far:
{history_str}

PROHIBITED QUESTIONS (You are forbidden from repeating, rephrasing, or asking these again):
{already_asked_list}

Instruction:
1. Act entirely as a human engineer chatting casually. DO NOT sound like a robot or formal recruiter. Use conversational phrasing like "So I noticed...", "I was looking at your background and...", or "I'm curious about...".
2. {difficulty_instruction}
3. The interview questions must center heavily on the candidate's actual projects, technical skills, experiences, and achievements listed on their resume, matching them against the Job Description. Ask them to explain specific decisions, technologies, or architectures they worked on in those projects.
4. Maintain a natural flow. If this is a follow-up, pivot naturally based on their last answer. If they struggled, say "No worries, let's switch gears..." and ask about a different project or skill from their resume.
5. NEVER repeat any of the PROHIBITED QUESTIONS listed above.
6. Make the question sound completely unscripted. It must be spoken naturally and be no longer than 25 words.
7. Return ONLY the spoken text of the next question. Do not include any quotes, preamble, or metadata.
"""
        try:
            return self._chat_text(prompt, temperature=0.85)
        except Exception as e:
            print(f"Groq Error (generate_next_question): {e}")
            return "Can you explain the technical architecture of a complex project you've led recently?"



# Backwards-compatible alias so existing imports keep working
GeminiExtractionService = GroqAIService
