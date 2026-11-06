"""Student login = registration number; superuser remains ADMIN."""
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class AttendanceUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields['role'] = 'ADMIN'
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrator'
        LECTURER = 'LECTURER', 'Lecturer'
        STUDENT = 'STUDENT', 'Student'

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    must_change_password = models.BooleanField(default=False)
    objects = AttendanceUserManager()

    def __str__(self):
        return self.username
