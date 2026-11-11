"""manage.py sync_tns_values --bot <name or TNS id> --user <username> (#52, plan 052 amendments 20-21)

Refreshes the TNS values (groups, filters, instruments, ...) from this deployment's TNS
(settings.TNS_TARGET) as one bot, and links every TNS group to an observation group. The same as
"Refresh from TNS" on the select page, without its 10-minute spacing. --user is who the change is
recorded as, including any observation groups it creates.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from YSE_App import tns_client, tns_values
from YSE_App.models import TNSBot


class Command(BaseCommand):
    help = "Refresh the TNS values from TNS as one bot, and link TNS groups to observation groups."

    def add_arguments(self, parser):
        parser.add_argument('--bot', required=True, help="The bot's name or TNS id (Admin > TNS bots)")
        parser.add_argument('--user', required=True, help='Username the change is recorded as')

    def handle(self, *args, **options):
        wanted = options['bot'].strip()
        bot = (TNSBot.objects.filter(tns_id=int(wanted)).first() if wanted.isdigit()
               else TNSBot.objects.filter(name__iexact=wanted).first())
        if bot is None:
            raise CommandError('No TNS bot %r (Admin > TNS bots)' % wanted)
        user = User.objects.filter(username=options['user']).first()
        if user is None:
            raise CommandError('No user %r' % options['user'])
        try:
            summary = tns_values.refresh(bot, user, gap=None)
        except tns_client.TNSError as e:
            raise CommandError('TNS did not answer as expected: %s' % e)
        self.stdout.write(tns_values.summary_text(summary))
        for kind, renames in sorted(summary['relabelled'].items()):
            for rename in renames:
                self.stdout.write('  relabelled %s %s' % (kind, rename))
        for kind, ids in sorted(summary['unlisted'].items()):
            self.stdout.write('  no longer listed: %s %s' % (kind, ', '.join(ids)))
        for what in ('linked', 'skipped'):
            for line in summary['obs_groups'].get(what, ()):
                self.stdout.write('  observation group %s: %s' % (what, line))
