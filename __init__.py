from flask import render_template, request, url_for, Markup
from sqlalchemy.sql import not_

from CTFd.admin import admin
from CTFd.models import Challenges, Tracking, Users
from CTFd.utils import get_config
from CTFd.utils.decorators import admins_only, is_admin
from CTFd.utils.modes import TEAMS_MODE
from CTFd.plugins import register_plugin_assets_directory
from CTFd.utils.plugins import override_template
import os
from collections import defaultdict,Counter
from statistics import pstdev

def process_submission(s, sc, sd, correct):
    try:
        missing = False

        class S:  # Wrapper for missing submission since those are Challenges only and not Submissions objects
            def __init__(self, c):
                self.challenge = c
                self.challenge_id = self.challenge.id
                self.provided = f"[Not answered yet]"
                self.date = None

        if (isinstance(s, Challenges)):
            s = S(s)
            missing = True
        scenario, new_name = s.challenge.name.split("-", 1)
        scenario = scenario.strip()
        if missing and scenario in sc and s.challenge_id in sc[scenario]: # Need to be careful not to add to defaultdict
            sc[scenario][s.challenge_id]['solved'] = False  # If the question is listed in missing
            return
        if missing and not s.challenge.state == 'visible':
            return  # Do not include hidden questions if missing
        if missing and scenario not in sc:
            return # Do not include if no questions from scenario are attempted
        if s.challenge_id not in sc[scenario]:
            sc[scenario][s.challenge_id]['name'] = new_name.strip()
            sc[scenario][s.challenge_id]['challenge_id'] = s.challenge_id
            sc[scenario][s.challenge_id]['category'] = s.challenge.category
            sc[scenario][s.challenge_id]['solved'] = False
            sc[scenario][s.challenge_id]['correct_first_time'] = False
            sc[scenario][s.challenge_id]['hidden'] = not s.challenge.state == 'visible'
            sc[scenario][s.challenge_id]['missing'] = missing
            sc[scenario][s.challenge_id]['value'] = s.challenge.value
            sc[scenario][s.challenge_id]['question'] = Markup(s.challenge.description)
            sc[scenario][s.challenge_id]['correct_answers'] = ", ".join([flag.content for flag in s.challenge.flags])
            sc[scenario][s.challenge_id]['submissions'] = list()
        sc[scenario][s.challenge_id]['submissions'].append({'submission': s.provided, 'correct': correct})

        if s.date is not None:
            if 'start_date' in sd[scenario] and 'end_date' in sd[scenario]:
                if s.date<sd[scenario]['start_date']:
                    sd[scenario]['start_date'] = s.date
                if s.date>sd[scenario]['end_date']:
                    sd[scenario]['end_date'] = s.date
            else:
                sd[scenario]['end_date']=s.date
                sd[scenario]['start_date'] = s.date
            sd[scenario]['time_delta']=sd[scenario]['end_date']-sd[scenario]['start_date']

        if correct:
            sc[scenario][s.challenge_id]['solved'] = True
            if len(sc[scenario][s.challenge_id]['submissions'])==1:
                sc[scenario][s.challenge_id]['correct_first_time']=True
    except ValueError:
        pass

def get_scenario_statistics(scenarios):

    by_category = defaultdict(lambda: Counter({'correct': 0, 'incorrect': 0, 'missing': 0, 'correct_first_time': 0}))
    by_scenario = defaultdict(lambda: defaultdict(lambda: Counter({'correct': 0, 'incorrect': 0, 'missing': 0, 'correct_first_time': 0})))

    for scenario,challenges in scenarios.items():
        for challenge,challenge_details in challenges.items():
            if challenge_details['correct_first_time']:
                by_category[challenge_details['category']].update(['correct_first_time'])
                by_scenario[scenario][challenge_details['category']].update(['correct_first_time'])
            elif challenge_details['solved']:
                by_category[challenge_details['category']].update(['correct'])
                by_scenario[scenario][challenge_details['category']].update(['correct'])
            elif not challenge_details['solved'] and not challenge_details['missing']:
                by_category[challenge_details['category']].update(['incorrect'])
                by_scenario[scenario][challenge_details['category']].update(['incorrect'])
            elif challenge_details['missing']:
                by_category[challenge_details['category']].update(['missing'])
                by_scenario[scenario][challenge_details['category']].update(['missing'])
    return by_scenario,by_category


def get_scenarios(fails, solves, missing):
    from collections import defaultdict
    scenario_challenges = defaultdict(lambda: defaultdict(dict))
    scenario_dates = defaultdict(dict)
    for f in fails:
        process_submission(f, scenario_challenges, scenario_dates, False)
    for s in solves:
        process_submission(s, scenario_challenges, scenario_dates, True)
    for m in missing:
        process_submission(m, scenario_challenges, scenario_dates, False)

    return scenario_challenges,scenario_dates

@admin.route("/admin/users/<int:user_id>")
@admins_only
def custom_users_detail(user_id):
    # Get user object
    scenarios=dict()
    scenario_dates=dict()
    by_scenario=dict()
    by_category=dict()

    all_users = (Users.query.filter_by(banned=False, hidden=False))
    specified_user = Users.query.filter_by(id=user_id).first_or_404()
    for user in all_users:
        #user = Users.query.filter_by(id=user_id).first_or_404()
        # Get the user's solves
        solves = user.get_solves(admin=True)
        all_solves = solves

        solve_ids = [s.challenge_id for s in all_solves]
        missing = Challenges.query.filter(not_(Challenges.id.in_(solve_ids))).all()

        # Get IP addresses that the User has used
        addrs = (
            Tracking.query.filter_by(user_id=user_id).order_by(Tracking.date.desc()).all()
        )

        # Get Fails
        fails = user.get_fails(admin=True)

        # Get Awards
        awards = user.get_awards(admin=True)

        # Get user properties
        score = user.get_score(admin=True)
        place = user.get_place(admin=True)

        scenarios[user], scenario_dates[user] = get_scenarios(fails, solves, missing)
        by_scenario[user],by_category[user]=get_scenario_statistics(scenarios[user])

    user=specified_user
    solves = user.get_solves(admin=True)

    # Get challenges that the user is missing
    if get_config("user_mode") == TEAMS_MODE:
        if user.team:
            all_solves = user.team.get_solves(admin=True)
        else:
            all_solves = user.get_solves(admin=True)
    else:
        all_solves = user.get_solves(admin=True)

    solve_ids = [s.challenge_id for s in all_solves]
    missing = Challenges.query.filter(not_(Challenges.id.in_(solve_ids))).all()

    # Get IP addresses that the User has used
    addrs = (
        Tracking.query.filter_by(user_id=user_id).order_by(Tracking.date.desc()).all()
    )

    # Get Fails
    fails = user.get_fails(admin=True)

    # Get Awards
    awards = user.get_awards(admin=True)

    # Get user properties
    score = user.get_score(admin=True)
    place = user.get_place(admin=True)

    scenarios[user], scenario_dates[user] = get_scenarios(fails, solves, missing)
    by_scenario[user], by_category[user] = get_scenario_statistics(scenarios[user])

    challenge_to_list_of_number_of_submissions = defaultdict(list)

    for person,person_scenario in scenarios.items():
        for scenario_name,s_item in person_scenario.items():
            for challenge in s_item.values():
                if challenge['solved']:
                    challenge_to_list_of_number_of_submissions[challenge['challenge_id']].append(len(challenge['submissions']))

                else:
                    challenge_to_list_of_number_of_submissions[challenge['challenge_id']].append(len(challenge['submissions'])+1)

    for scenario_name,s_item in scenarios[specified_user].items():
        for challenge_id,challenge in s_item.items():
            challenge['average']=sum(challenge_to_list_of_number_of_submissions[challenge['challenge_id']])/len(challenge_to_list_of_number_of_submissions[challenge['challenge_id']])
            challenge['stdev'] = pstdev(challenge_to_list_of_number_of_submissions[challenge['challenge_id']])
            if challenge['stdev']!=0 and challenge['solved']==True:
                challenge['zscore'] = (len(challenge['submissions'])-challenge['average'])/challenge['stdev']
            elif challenge['solved']==True:
                challenge['zscore'] = 0
            else:
                challenge['zscore'] = None
                #might not really be the zscore but that is okay

    #print (scenarios[specified_user])

    return render_template(
        "admin/users/user.html",
        solves=solves,
        user=user,
        addrs=addrs,
        score=score,
        missing=missing,
        place=place,
        fails=fails,
        awards=awards,
        scenarios=scenarios[specified_user],
        scenario_dates=scenario_dates[specified_user],
        stats_by_scenario=by_scenario[specified_user],
        stats_by_category=by_category[specified_user],
    )


def load(app):
    #register_plugin_assets_directory(app, base_path='/plugins/scenario_user_reports/assets/')

    dir_path = os.path.dirname(os.path.realpath(__file__))
    template_path = os.path.join(dir_path, 'custom_user.html')
    override_template('admin/users/user.html', open(template_path).read())

    app.view_functions['admin.users_detail'] = custom_users_detail
