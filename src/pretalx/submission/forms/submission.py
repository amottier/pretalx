from django import forms
from django.conf import settings
from django.db.models import Count
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django_scopes.forms import SafeModelChoiceField

from pretalx.cfp.forms.cfp import CfPFormMixin
from pretalx.common.forms.fields import ImageField
from pretalx.common.forms.widgets import MarkdownWidget
from pretalx.common.mixins.forms import PublicContent, RequestRequire
from pretalx.submission.forms.track_select_widget import TrackSelectWidget
from pretalx.submission.models import Question, Submission, SubmissionStates


class InfoForm(CfPFormMixin, RequestRequire, PublicContent, forms.ModelForm):
    additional_speaker = forms.EmailField(
        label=_("Additional Speaker"),
        help_text=_(
            "If you have a co-speaker, please add their email address here, and we will invite them to create an account. If you have more than one co-speaker, you can add more speakers after finishing the proposal process."
        ),
        required=False,
    )
    image = ImageField(
        required=False,
        label=_("Session image"),
        help_text=_("Use this if you want an illustration to go with your proposal."),
    )

    def __init__(self, event, **kwargs):
        self.event = event
        self.readonly = kwargs.pop("readonly", False)
        self.access_code = kwargs.pop("access_code", None)
        self.default_values = {}
        instance = kwargs.get("instance")
        initial = kwargs.pop("initial", {}) or {}
        if not instance or not instance.submission_type:
            initial["submission_type"] = (
                getattr(self.access_code, "submission_type", None)
                or initial.get("submission_type")
                or self.event.cfp.default_type
            )
        if not instance and self.access_code:
            initial["track"] = self.access_code.track
        if not instance or not instance.content_locale:
            initial["content_locale"] = self.event.locale

        super().__init__(initial=initial, **kwargs)

        if "abstract" in self.fields:
            self.fields["abstract"].widget.attrs["rows"] = 2
        if (instance and instance.pk) or not self.event.cfp.request_additional_speaker:
            self.fields.pop("additional_speaker")

        self._set_track(instance=instance)
        self._set_submission_types(instance=instance)
        self._set_locales()
        self._set_slot_count(instance=instance)

        if self.readonly:
            for f in self.fields.values():
                f.disabled = True

    def _set_track(self, instance=None):
        if "track" in self.fields:
            if (
                not self.event.feature_flags["use_tracks"]
                or instance
                and instance.state != SubmissionStates.SUBMITTED
            ):
                self.fields.pop("track")
                return

            access_code = self.access_code or getattr(instance, "access_code", None)
            if not access_code or not access_code.track:
                self.fields["track"].queryset = self.event.tracks.filter(
                    requires_access_code=False
                )
            else:
                self.fields["track"].queryset = self.event.tracks.filter(
                    pk=access_code.track.pk
                )
            if (
                len(self.fields["track"].queryset) == 1
                and self.fields["track"].required
            ):
                self.default_values["track"] = self.fields["track"].queryset.first()
                self.fields.pop("track")

    def _set_submission_types(self, instance=None):
        _now = now()
        if (
            instance
            and instance.pk
            and (
                instance.state != SubmissionStates.SUBMITTED
                or not self.event.cfp.is_open
            )
        ):
            self.fields[
                "submission_type"
            ].queryset = self.event.submission_types.filter(
                pk=instance.submission_type_id
            )
            self.fields["submission_type"].disabled = True
            return
        access_code = self.access_code or getattr(instance, "access_code", None)
        if access_code and not access_code.submission_type:
            pks = set(self.event.submission_types.values_list("pk", flat=True))
        elif access_code:
            pks = {access_code.submission_type.pk}
        else:
            queryset = self.event.submission_types.filter(requires_access_code=False)
            if (
                not self.event.cfp.deadline or self.event.cfp.deadline >= _now
            ):  # No global deadline or still open
                types = queryset.exclude(deadline__lt=_now)
            else:
                types = queryset.filter(deadline__gte=_now)
            pks = set(types.values_list("pk", flat=True))
        if instance and instance.pk:
            pks |= {instance.submission_type.pk}
        self.fields["submission_type"].queryset = self.event.submission_types.filter(
            pk__in=pks
        )
        if len(pks) == 1:
            self.default_values["submission_type"] = self.event.submission_types.get(
                pk=list(pks)[0]
            )
            self.fields.pop("submission_type")

    def _set_locales(self):
        if "content_locale" in self.fields:
            if len(self.event.locales) == 1:
                self.default_values["content_locale"] = self.event.locales[0]
                self.fields.pop("content_locale")
            else:
                locale_names = dict(settings.LANGUAGES)
                self.fields["content_locale"].choices = [
                    (a, locale_names[a]) for a in self.event.locales
                ]

    def _set_slot_count(self, instance=None):
        if not self.event.feature_flags["present_multiple_times"]:
            self.fields.pop("slot_count", None)
        elif (
            "slot_count" in self.fields
            and instance
            and instance.state
            in [SubmissionStates.ACCEPTED, SubmissionStates.CONFIRMED]
        ):
            self.fields["slot_count"].disabled = True
            self.fields["slot_count"].help_text += " " + str(
                _(
                    "Please contact the organisers if you want to change how often you're presenting this proposal."
                )
            )

    def save(self, *args, **kwargs):
        for key, value in self.default_values.items():
            setattr(self.instance, key, value)
        return super().save(*args, **kwargs)

    class Meta:
        model = Submission
        fields = [
            "title",
            "submission_type",
            "track",
            "content_locale",
            "abstract",
            "description",
            "notes",
            "slot_count",
            "do_not_record",
            "image",
            "duration",
        ]
        request_require = [
            "title",
            "abstract",
            "description",
            "notes",
            "image",
            "do_not_record",
            "track",
            "duration",
            "content_locale",
        ]
        public_fields = ["title", "abstract", "description", "image"]
        widgets = {
            "abstract": MarkdownWidget,
            "description": MarkdownWidget,
            "notes": MarkdownWidget,
            "track": TrackSelectWidget,
        }
        field_classes = {
            "submission_type": SafeModelChoiceField,
            "track": SafeModelChoiceField,
        }


class SelectMultipleWithCount(forms.SelectMultiple):
    """A widget for multi-selects that correspond to countable values.

    This widget doesn't support some of the options of the default
    SelectMultiple, most notably it doesn't support optgroups. In
    return, it takes a third value per choice, makes zero-values
    disabled and sorts options by numerical value.
    """

    def optgroups(self, name, value, attrs=None):
        choices = sorted(self.choices, key=lambda x: x[1].count, reverse=True)
        result = []
        for index, (option_value, label) in enumerate(choices):
            selected = str(option_value) in value
            result.append(
                self.create_option(
                    name,
                    value=option_value,
                    label=label,
                    selected=selected,
                    index=index,
                )
            )
        return [(None, result, 0)]

    def create_option(self, name, value, label, *args, count=0, **kwargs):
        option = super().create_option(name, value, str(label), *args, **kwargs)
        if label.count == 0:
            option["attrs"]["class"] = "hidden"
        return option


class CountableOption:
    def __init__(self, name, count):
        self.name = name
        self.count = count

    def __str__(self):
        return f"{self.name} ({self.count})"


class SubmissionFilterForm(forms.Form):
    state = forms.MultipleChoiceField(
        required=False,
        widget=SelectMultipleWithCount(
            attrs={"class": "select2", "title": _("Proposal states")}
        ),
        choices=SubmissionStates.get_choices(),
    )
    submission_type = forms.MultipleChoiceField(
        required=False,
        widget=SelectMultipleWithCount(
            attrs={"class": "select2", "title": _("Session types")}
        ),
    )
    pending_state__isnull = forms.BooleanField(
        required=False,
        label=_("exclude pending"),
    )
    track = forms.MultipleChoiceField(
        required=False,
        widget=SelectMultipleWithCount(
            attrs={"class": "select2", "title": _("Tracks")}
        ),
    )
    tags = forms.MultipleChoiceField(
        required=False,
        widget=SelectMultipleWithCount(attrs={"class": "select2", "title": _("Tags")}),
    )
    question = SafeModelChoiceField(queryset=Question.objects.none(), required=False)

    def __init__(self, event, *args, limit_tracks=False, **kwargs):
        self.event = event
        usable_states = kwargs.pop("usable_states", None)
        initial = kwargs.pop("initial", {}) or {}
        initial["exclude_pending"] = False
        super().__init__(*args, initial=initial, **kwargs)
        qs = event.submissions
        state_qs = Submission.objects.filter(event=event)
        if usable_states:
            qs = qs.filter(state__in=usable_states)
            state_qs = state_qs.filter(state__in=usable_states)
        state_count = {
            d["state"]: d["state__count"]
            for d in state_qs.order_by("state").values("state").annotate(Count("state"))
        }
        state_count.update(
            {
                f"pending_state__{d['pending_state']}": d["pending_state__count"]
                for d in state_qs.filter(pending_state__isnull=False)
                .order_by("pending_state")
                .values("pending_state")
                .annotate(Count("pending_state"))
            }
        )
        sub_types = event.submission_types.all()
        tracks = limit_tracks or event.tracks.all()
        if len(sub_types) > 1:
            type_count = {
                d["submission_type_id"]: d["submission_type_id__count"]
                for d in qs.order_by("submission_type_id")
                .values("submission_type_id")
                .annotate(Count("submission_type_id"))
            }
            self.fields["submission_type"].choices = [
                (
                    sub_type.pk,
                    CountableOption(sub_type.name, type_count.get(sub_type.pk, 0)),
                )
                for sub_type in sub_types
            ]
        else:
            self.fields.pop("submission_type", None)
        if len(tracks) > 1:
            track_count = {
                d["track"]: d["track__count"]
                for d in qs.order_by("track").values("track").annotate(Count("track"))
            }
            self.fields["track"].choices = [
                (track.pk, CountableOption(track.name, track_count.get(track.pk, 0)))
                for track in tracks
            ]
        else:
            self.fields.pop("track", None)

        if not self.event.tags.all().exists():
            self.fields.pop("tags", None)
        else:
            tag_count = event.tags.prefetch_related("submissions").annotate(
                submission_count=Count("submissions", distinct=True)
            )
            tag_count = {tag.tag: tag.submission_count for tag in tag_count}
            self.fields["tags"].choices = [
                (tag.pk, CountableOption(tag.tag, tag_count.get(tag.tag, 0)))
                for tag in self.event.tags.all()
            ]

        if usable_states:
            usable_states = [
                choice
                for choice in self.fields["state"].choices
                if choice[0] in usable_states
            ]
        else:
            usable_states = self.fields["state"].choices
        usable_states += [
            (
                f"pending_state__{choice[0]}",
                str(_("Pending {state}")).format(state=choice[1]),
            )
            for choice in usable_states
        ]
        self.fields["state"].choices = [
            (
                choice[0],
                CountableOption(choice[1].capitalize(), state_count.get(choice[0], 0)),
            )
            for choice in usable_states
        ]
        self.fields["question"].queryset = event.questions.all()
