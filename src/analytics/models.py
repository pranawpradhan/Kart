from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import models
from django.db.models.signals import post_save

from .signals import object_viewed_signal
from .utils import get_client_ip
from accounts.signals import user_session_signal


User = settings.AUTH_USER_MODEL

# To disable the post_save connectors
FORCE_SESSION_TO_ONE = getattr(settings, 'FORCE_SESSION_TO_ONE', False)
FORCE_INACTIVE_USER_END_SESSION = getattr(settings, 'FORCE_INACTIVE_USER_END_SESSION', False)


class ObjectViewed(models.Model):
    user = models.ForeignKey(User, blank=True, null=True)  # null/blank is enabled because we also want to track guest
    # We can use an IpField but then various systems have different permissions and we would have to handle all that
    ip_address = models.CharField(max_length=220, blank=True, null=True)

    # The following three generic fields can be replaced by a field for each specific model or by a single url field
    content_type = models.ForeignKey(ContentType)  # Has the content of the specified model
    object_id = models.PositiveIntegerField()  # Has the object id for model specified above
    content_object = GenericForeignKey('content_type', 'object_id')  # Has the instance of the object of model selected

    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return '%s viewed on %s' % (self.content_object, self.timestamp)

    class Meta:
        ordering = ['-timestamp']  # Most recently saved showed first
        verbose_name = 'Object viewed'
        verbose_name_plural = 'Objects viewed'


def object_viewed_receiver(sender, instance, request, *args, **kwargs):
    # args/kwargs are used to get any other default parameters
    # print(sender)
    # print(instance)
    # print(request)
    # print(request.user)
    content_type = ContentType.objects.get_for_model(sender)  # instance.__class__
    new_view_obj = ObjectViewed.objects.create(
        user=request.user,
        ip_address=get_client_ip(request),
        content_type=content_type,
        object_id=instance.id
    )

# no need to include sender as a parameter because that is already passed along with the signal
object_viewed_signal.connect(object_viewed_receiver)


class UserSession(models.Model):
    user = models.ForeignKey(User, blank=True, null=True)
    ip_address = models.CharField(max_length=220, blank=True, null=True)
    session_key = models.CharField(max_length=100, blank=True, null=True)  # min length 50
    timestamp = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)  # session active
    ended = models.BooleanField(default=False)  # session ended --> logged out

    def __str__(self):
        return self.user.email

    def end_session(self):
        try:
            Session.objects.get(pk=self.session_key).delete()
            self.ended = True
            self.active = False
            self.save()
        except:
            pass
        return self.ended


def user_session_receiver(sender, instance, request, *args, **kwargs):
    UserSession.objects.create(
        user=instance,
        ip_address=get_client_ip(request),
        session_key=request.session.session_key  # Django 1.11
    )

user_session_signal.connect(user_session_receiver)


def post_save_session_receiver(sender, instance, created, *args, **kwargs):
    if created:
        # When user logs in, delete all the sessions related to the user except the current one
        qs = UserSession.objects.filter(user=instance.user).exclude(id=instance.id)
        for session in qs:
            session.end_session()

    if not instance.active and not instance.ended:
        instance.end_session()

if FORCE_SESSION_TO_ONE:
    post_save.connect(post_save_session_receiver, sender=UserSession)


def post_save_user_changed_receiver(sender, instance, created, *args, **kwargs):
    if not created:
        # if user becomes inactive, delete all of its inactive sessions
        if not instance.is_active:
            qs = UserSession.objects.filter(user=instance.user, ended=False, active=False)
            for session in qs:
                session.end_session()

if FORCE_INACTIVE_USER_END_SESSION:
    post_save.connect(post_save_user_changed_receiver, sender=User)
