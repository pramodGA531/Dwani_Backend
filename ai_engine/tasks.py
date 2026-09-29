from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

@shared_task
def send_email_task(subject, template_name, context, recipient_list, plain_text=None):
    try:
        html_content = render_to_string(template_name, context)

        # Build a meaningful plain-text fallback if not provided
        if not plain_text:
            invite_link = context.get('invite_link') or context.get('login_url', '')
            plain_text = (
                f"{subject}\n\n"
                f"Hello {context.get('email') or context.get('name', 'there')},\n\n"
                f"{context.get('job_title', '')}\n\n"
                + (f"Interview link: {invite_link}\n\n" if invite_link else "")
                + "This is a transactional email from DwaniAI Hiring Platform.\n"
                "Please do not reply to this email.\n"
            )

        email = EmailMultiAlternatives(
            subject=subject,
            body=plain_text,
            from_email=f"DwaniAI Hiring <{settings.DEFAULT_FROM_EMAIL}>",
            to=recipient_list,
            headers={
                "List-Unsubscribe": f"<mailto:{settings.DEFAULT_FROM_EMAIL}?subject=unsubscribe>",
                "X-Mailer": "DwaniAI Hiring Platform",
            }
        )
        email.attach_alternative(html_content, "text/html")

        # Always print credentials to server log as a fallback
        if 'temp_password' in context and context['temp_password']:
            print(f"\n{'='*60}")
            print(f"[EMAIL DEBUG] Sending invite to: {recipient_list}")
            print(f"[EMAIL DEBUG] Subject: {subject}")
            print(f"[EMAIL DEBUG] Candidate Email: {context.get('email')}")
            print(f"[EMAIL DEBUG] Temp Password:   {context['temp_password']}")
            print(f"[EMAIL DEBUG] Invite Link:     {context.get('invite_link', 'N/A')}")
            print(f"{'='*60}\n")

        email.send()
        print(f"[EMAIL] Successfully sent '{subject}' to {recipient_list}")
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send '{subject}' to {recipient_list}: {e}")
        return False
