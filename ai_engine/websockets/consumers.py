import json
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from django.utils import timezone
# pyrefly: ignore [missing-import]
from ai_engine.models import Interview, Response
from ai_engine.services.groq_service import GroqAIService


class InterviewConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.session_token = self.scope['url_route']['kwargs']['session_token']

        # ── JWT auth from query string (?token=...) ──────────────────
        user = await self.get_user_from_query()
        if user is None:
            await self.close(code=4001)
            return

        # ── Validate interview session ────────────────────────────────
        self.interview = await self.get_interview(self.session_token)
        if not self.interview:
            await self.close(code=4004)
            return

        # Use the actual interview's session token to ensure recruiter (connecting via ID)
        # joins the exact same room as the candidate (connecting via UUID).
        self.room_group_name = f'interview_{self.interview.session_token}'

        # ── Check link expiry ─────────────────────────────────────────
        expired = await self.is_expired()
        if expired:
            await self.close(code=4003)
            return

        # ── Join the channel group ────────────────────────────────────
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            event_type = data.get('type')

            if event_type == 'session_start':
                await self.handle_session_start()
            elif event_type == 'answer':
                await self.handle_answer(data)
            elif event_type == 'end_session':
                await self.handle_end_session()
        except Exception as e:
            await self.send(text_data=json.dumps({'type': 'error', 'message': str(e)}))

    # ── Event handlers ────────────────────────────────────────────────

    async def handle_session_start(self):
        await self.update_interview_status('in_progress')
        question_text = await self.generate_next_question(None, None)
        await self.channel_layer.group_send(self.room_group_name, {
            'type': 'question_event',
            'question_index': 1,
            'question_text': question_text,
        })

    async def handle_answer(self, data):
        answer_text = data.get('answer_text', '')
        question_index = data.get('question_index', 1)
        question_text = data.get('question_text', '')

        # Score answer
        evaluation = await self.evaluate_answer(question_text, answer_text)

        # Persist response
        await self.save_response(question_index, question_text, answer_text, evaluation)

        # Broadcast answer evaluation
        await self.channel_layer.group_send(self.room_group_name, {
            'type': 'answer_event',
            'question_index': question_index,
            'question_text': question_text,
            'answer_text': answer_text,
            'evaluation': evaluation,
        })

        # End after 5 questions
        if question_index >= 5:
            await self.update_interview_status('completed')
            await self.channel_layer.group_send(self.room_group_name, {
                'type': 'end_session_event',
                'message': 'Interview completed.'
            })
            return

        # Generate next question dynamically
        next_q = await self.generate_next_question(answer_text, evaluation.get('overall_score', 50))
        await self.channel_layer.group_send(self.room_group_name, {
            'type': 'question_event',
            'question_index': question_index + 1,
            'question_text': next_q,
        })

    async def handle_end_session(self):
        await self.update_interview_status('completed')
        await self.channel_layer.group_send(self.room_group_name, {
            'type': 'end_session_event',
            'message': 'Session ended.'
        })

    # ── Channel Group Event Handlers ──────────────────────────────────
    async def question_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'question',
            'question_index': event['question_index'],
            'question_text': event['question_text'],
        }))

    async def answer_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'answer',
            'question_index': event['question_index'],
            'question_text': event['question_text'],
            'answer_text': event['answer_text'],
            'evaluation': event['evaluation'],
        }))

    async def end_session_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'end_session',
            'message': event['message'],
        }))

    async def anomaly_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'anomaly_event',
            'event_type': event['event_type'],
            'severity': event['severity'],
            'snapshot_url': event['snapshot_url'],
            'timestamp': event['timestamp'],
            'is_termination': event['is_termination']
        }))

    # ── DB helpers ────────────────────────────────────────────────────

    @sync_to_async
    def get_user_from_query(self):
        """Extract and verify JWT token from ?token= query string."""
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            from django.contrib.auth import get_user_model
            User = get_user_model()

            qs = parse_qs(self.scope.get('query_string', b'').decode())
            jwt = qs.get('token', [None])[0]
            if not jwt:
                return None
            payload = AccessToken(jwt)
            return User.objects.get(id=payload['user_id'])
        except Exception:
            return None

    @sync_to_async
    def get_interview(self, token):
        from django.db.models import Q
        try:
            try:
                interview_id = int(token)
                query = Q(id=interview_id) | Q(session_token=token)
            except ValueError:
                query = Q(session_token=token)
            return Interview.objects.select_related('job', 'candidate').get(query)
        except Interview.DoesNotExist:
            return None

    @sync_to_async
    def is_expired(self):
        if self.interview.link1_expiry and self.interview.link1_expiry < timezone.now():
            return True
        return False

    @sync_to_async
    def update_interview_status(self, status):
        self.interview.status = status
        self.interview.save(update_fields=['status'])

    @sync_to_async
    def save_response(self, question_index, question_text, answer_text, evaluation):
        Response.objects.create(
            interview=self.interview,
            question_index=question_index,
            question_text=question_text,
            answer_text=answer_text,
            relevance_score=evaluation.get('relevance_score'),
            accuracy_score=evaluation.get('accuracy_score'),
            clarity_score=evaluation.get('clarity_score'),
        )

    @sync_to_async
    def generate_next_question(self, previous_answer, previous_score):
        service = GroqAIService()
        return service.generate_next_question(
            interview=self.interview,
            previous_answer=previous_answer,
            previous_score=previous_score,
        )

    @sync_to_async
    def evaluate_answer(self, question_text, answer_text):
        service = GroqAIService()
        return service.evaluate_answer(question_text, answer_text)
