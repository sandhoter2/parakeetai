from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import InterviewSession, UserProfile


class NewSessionForm(forms.ModelForm):
    class Meta:
        model = InterviewSession
        fields = ["session_type", "title", "company", "language", "job_description", "meeting_agenda", "extra_context"]
        widgets = {
            "session_type": forms.RadioSelect(attrs={"class": "session-type-radio"}),
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. TIBCO Integration Architect — System Design Review",
            }),
            "company": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. TIBCO Software, Broadcom",
            }),
            "language": forms.Select(attrs={"class": "form-control"}),
            "job_description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Describe the job description or interview context.",
            }),
            "meeting_agenda": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Agenda items, topics to cover, goals for the meeting…",
            }),
            "extra_context": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 6,
                "placeholder": "Your skills, experience, past projects, achievements…",
            }),
        }
        labels = {
            "session_type": "Session Type",
            "title": "Role / Meeting Title",
            "company": "Company / Team",
            "job_description": "Job Description / Interview Context",
            "meeting_agenda": "Meeting Agenda",
            "extra_context": "Your Background / Resume",
        }


class UserProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))

    class Meta:
        model = UserProfile
        fields = ["display_name", "role", "company", "background"]
        widgets = {
            "display_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "How you'd like to be called"}),
            "role": forms.Select(attrs={"class": "form-control"}),
            "company": forms.TextInput(attrs={"class": "form-control", "placeholder": "Your company or team"}),
            "background": forms.Textarea(attrs={
                "class": "form-control", "rows": 8,
                "placeholder": "Resume summary, skills, experience — this auto-populates the background field in new sessions.",
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email

    def save_user(self, user, commit=True):
        user.first_name = self.cleaned_data.get("first_name", "")
        user.last_name = self.cleaned_data.get("last_name", "")
        user.email = self.cleaned_data.get("email", "")
        if commit:
            user.save()
        return user


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={"class": "form-control"}))

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs["class"] = "form-control"
        self.fields["password2"].widget.attrs["class"] = "form-control"
