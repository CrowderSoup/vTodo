import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone as dj_timezone


class UserManager(BaseUserManager):
    def create_user(self, username=None, **extra_fields):
        if not username:
            username = uuid.uuid4().hex[:16]
        user = self.model(username=username, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        user = self.model(username=username)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    KIND_HUMAN = "human"
    KIND_AGENT = "agent"
    KIND_CHOICES = [
        (KIND_HUMAN, "Person"),
        (KIND_AGENT, "Agent"),
    ]

    # Auto-generated slug — never entered by humans.
    username = models.CharField(max_length=64, unique=True)

    # An agent is a sub-account of a person. It signs in only with an API
    # token, acts in its parent's workspaces, and can be assigned tasks.
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_HUMAN)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="agents",
    )

    display_name = models.CharField(max_length=255, blank=True, default="")
    avatar_url = models.URLField(max_length=2000, blank=True, default="")

    default_status = models.ForeignKey(
        "tasks.TaskStatus",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_for_users",
    )

    # IANA zone name (e.g. "America/Chicago"), used to compute "today"/overdue
    # and recurrence dates in the user's own local time instead of UTC.
    timezone = models.CharField(max_length=64, default="UTC")

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=dj_timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind="human", parent__isnull=True)
                    | models.Q(kind="agent", parent__isnull=False)
                ),
                name="user_agent_has_parent",
            ),
        ]

    def __str__(self):
        return self.display_name or self.username

    @property
    def is_agent(self):
        return self.kind == self.KIND_AGENT

    @property
    def account(self):
        """The person this user acts for: an agent's parent, else themselves."""
        return self.parent if self.is_agent else self
