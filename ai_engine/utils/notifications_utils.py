import threading
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

def send_html_email(subject, template_name, context, recipient_list, plain_text=None):
    from ai_engine.tasks import send_email_task
    
    # Fire off to Celery in the background
    send_email_task.delay(
        subject=subject,
        template_name=template_name,
        context=context,
        recipient_list=recipient_list,
        plain_text=plain_text
    )

def send_approval_email(user):
    """Send approval email to a recruiter whose account has been approved."""
    send_html_email(
        subject="Your recruiter account has been approved!",
        template_name="emails/approval_email.html",
        context={
            'login_url': f"{settings.FRONTEND_URL}/login",
            'email': user.email,
        },
        recipient_list=[user.email]
    )

def send_rejection_email(user, reason=''):
    """Send rejection email to a recruiter whose account was rejected."""
    send_html_email(
        subject="Your recruiter account request was not approved",
        template_name="emails/rejection_email.html",
        context={
            'email': user.email,
            'reason': reason or 'Your account did not meet our approval criteria.',
        },
        recipient_list=[user.email]
    )
def send_new_recruiter_notification(user):
    """Send an alert email to the admin when a new recruiter registers."""
    # Django Admin URL for user management
    admin_url = "http://localhost:8000/admin/users/user/" 
    
    send_html_email(
        subject="New Recruiter Registration Awaiting Approval",
        template_name="emails/admin_new_recruiter.html",
        context={
            'recruiter_email': user.email,
            'admin_url': admin_url,
        },
        recipient_list=[settings.DEFAULT_FROM_EMAIL]
    )

def send_candidate_welcome_email(user, password):
    """Send welcome email to a candidate with their login credentials."""
    send_html_email(
        subject="Your AI Interview Invitation",
        template_name="emails/candidate_welcome.html",
        context={
            'name': user.email,
            'email': user.email,
            'password': password,
            'login_url': f"{settings.FRONTEND_URL}/",
        },
        recipient_list=[user.email]
    )

def send_candidate_completion_email(user, password):
    """Send email to candidate when interview completes, giving them the portal login to view report."""
    send_html_email(
        subject="Interview Completed - View Your Results",
        template_name="emails/candidate_completion.html",
        context={
            'name': user.email,
            'email': user.email,
            'password': password,
            'login_url': f"{settings.FRONTEND_URL}/",
            'temp_password': password  # just to log it in server console
        },
        recipient_list=[user.email]
    )

def send_candidate_accepted_email(user, job_title, candidate_name=None):
    """Send email to candidate when recruiter accepts them."""
    name = candidate_name or user.email.split('@')[0]
    send_html_email(
        subject=f"Congratulations! Next Steps for the {job_title} Position",
        template_name="emails/candidate_accepted.html",
        context={
            'name': name,
            'job_title': job_title,
        },
        recipient_list=[user.email]
    )

def send_candidate_rejected_email(user, job_title, candidate_name=None):
    """Send email to candidate when recruiter rejects them."""
    name = candidate_name or user.email.split('@')[0]
    send_html_email(
        subject=f"Update regarding your application for {job_title}",
        template_name="emails/candidate_rejected.html",
        context={
            'name': name,
            'job_title': job_title,
        },
        recipient_list=[user.email]
    )

