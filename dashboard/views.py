from functools import wraps
from flask import render_template, flash, url_for, redirect, request, jsonify, abort
from flask import session as flask_session
from flask_login import login_user, logout_user, current_user, \
    login_required, fresh_login_required
from sqlalchemy.exc import SQLAlchemyError
from dashboard import app, db, lm
from oauth import OAuthSignIn
from .queries import query_metric_values_byid, query_metric_types, query_metric_values_byname
from .models import Study, Site, Session, ScanType, Scan, User
from .forms import SelectMetricsForm, StudyOverviewForm, SessionForm, ScanForm, UserForm
from . import utils
import json
import csv
import io
import os
import codecs
import datetime
import datman as dm
import shutil
import logging
from github import Github
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)
logger.info('Loading views')


@lm.user_loader
def load_user(id):
    return User.query.get(id)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


@app.before_request
def before_request():
    if current_user.is_authenticated:
        db.session.add(current_user)
        db.session.commit()

@app.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('login'))

@app.route('/')
@app.route('/index')
@login_required
def index():
    # studies = db_session.query(Study).order_by(Study.nickname).all()
    studies = current_user.get_studies()

    session_count = Session.query.count()
    study_count = Study.query.count()
    site_count = Site.query.count()
    return render_template('index.html',
                           studies=studies,
                           session_count=session_count,
                           study_count=study_count,
                           site_count=site_count)

@app.route('/sites')
@login_required
def sites():
    pass


@app.route('/scantypes')
@login_required
def scantypes():
    pass

@app.route('/users')
@login_required
def users():
    if not current_user.is_admin:
        flash('You are not authorised')
        return redirect(url_for('user'))
    users = User.query.all()
    user_forms = []
    for user in users:
        form = UserForm()
        form.user_id.data = user.id
        form.realname.data = user.realname
        form.is_admin.data = user.is_admin
        form.has_phi.data = user.has_phi
        study_ids = [str(study.id) for study in user.studies]
        form.studies.data = study_ids
        user_forms.append(form)
    return render_template('users.html',
                           studies=current_user.get_studies(),
                           user_forms=user_forms)

@app.route('/user', methods=['GET', 'POST'])
@app.route('/user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def user(user_id=None):
    form = UserForm()

    if form.validate_on_submit():
        if form.user_id.data == current_user.id or current_user.is_admin:
            user = User.query.get(form.user_id.data)
            user.realname = form.realname.data
            if current_user.is_admin:
                # only admins can update this info
                user.is_admin = form.is_admin.data
                user.has_phi = form.has_phi.data
                for study_id in form.studies.data:
                    study = Study.query.get(int(study_id))
                    user.studies.append(study)
            db.session.add(user)
            db.session.commit()
            flash('User profile updated')
            return(redirect(url_for('user', user_id=user_id)))
        else:
            flash('You are not authorised to update this')
            return(redirect(url_for('user')))
    else:
        if user_id and current_user.is_admin:
            user = User.query.get(user_id)
        else:
            user = current_user

        user_studyids = [study.id for study in user.studies]

        form.user_id.data = user.id
        form.realname.data = user.realname
        form.is_admin.data = user.is_admin
        form.has_phi.data = user.has_phi
        form.studies.data = user_studyids
        if not current_user.is_admin:
            # disable some fields
            form.is_admin(disabled=True)
            form.has_phi(disabled=True)
            form.studies(disabled=True)
    return render_template('user.html',
                           user=user,
                           form=form)

@app.route('/session_by_name')
@app.route('/session_by_name/<session_name>', methods=['GET'])
@login_required
def session_by_name(session_name=None):
    if session_name is None:
        return redirect('/index')
    # Strip any file extension or qc_ prefix
    session_name = session_name.replace('qc_', '')
    session_name = os.path.splitext(session_name)[0]

    q = Session.query.filter(Session.name == session_name)
    if q.count() < 1:
        flash('Session not found')
        return redirect(url_for('index'))

    session = q.first()

    if not current_user.has_study_access(session.study):
        flash('Not authorised')
        return redirect(url_for('index'))

    return redirect(url_for('session', session_id=session.id))


@app.route('/create_issue/<int:session_id>', methods=['GET', 'POST'])
@app.route('/create_issue/<int:session_id>/<issue_title>/<issue_body>', methods=['GET', 'POST'])
@fresh_login_required
def create_issue(session_id, issue_title="", issue_body=""):
    session = Session.query.get(session_id)
    if not current_user.has_study_access(session.study):
        flash("Not authorised")
        return redirect(url_for('index'))

    token = flask_session['active_token']

    if issue_title and issue_body:
        try:
            gh = Github(token)
            repo = gh.get_user("TIGRLab").get_repo("Admin")
            iss = repo.create_issue(issue_title, issue_body)
            session.gh_issue = iss.number
            db.session.commit()
            flash("Issue '{}' created!".format(issue_title))
        except:
            flash("Issue '{}' was not created successfully.".format(issue_title))
    else:
        flash("Please enter both an issue title and description.")
    return(redirect(url_for('session', session_id=session.id)))

@app.route('/session')
@app.route('/session/<int:session_id>', methods=['GET', 'POST'])
@app.route('/session/<int:session_id>/<delete>', methods=['GET', 'POST'])
@login_required
def session(session_id=None, delete=False):
    if session_id is None:
        return redirect('index')

    session = Session.query.get(session_id)
    if not current_user.has_study_access(session.study):
        flash('Not authorised')
        return redirect(url_for('index'))
    try:
        # Update open issue ID if necessary
        token = flask_session['active_token']
    except:
        flash('It appears you\'ve been idle too long; please sign in again.')
        return redirect(url_for('login'))
    try:
        gh = Github(token)
        # Due to the way GitHub search API works, splitting session name into separate search terms will find a session
        # regardless of repeat number, and will not match other sessions with the same study/site
        open_issues = gh.search_issues("{} in:title repo:TIGRLab/admin state:open".format(str(session.name).replace("_"," ")))
        if open_issues.totalCount:
            session.gh_issue = open_issues[0].number
        else:
            session.gh_issue = None
        db.session.commit()
    except:
        flash("Error searching for session's GitHub issue.")

    if delete:
        try:
            db.session.delete(session)
            db.session.commit()
            flash('Deleted session:{}'.format(session.name))
            return redirect(url_for('study',
                                    study_id=session.study_id,
                                    active_tab='qc'))
        except Exception:
            flash('Failed to delete session:{}'.format(session.name))

    studies = current_user.get_studies()
    form = SessionForm(obj=session)

    if form.validate_on_submit():
        # form has been submitted
        session.cl_comment = form.cl_comment.data
        try:
            db.session.add(session)
            db.session.commit()
            flash('Session updated')
            return redirect(url_for('study',
                                    study_id=session.study_id,
                                    active_tab='qc'))

        except SQLAlchemyError as err:
            logger.error('Session update failed:{}'.format(str(err)))
            flash('Update failed, admins have been notified, please try again')
        form.populate_obj(session)

    return render_template('session.html',
                           studies=studies,
                           study=session.study,
                           session=session,
                           form=form)

@app.route('/scan', methods=["GET"])
@app.route('/scan/<int:scan_id>', methods=['GET', 'POST'])
@login_required
def scan(scan_id=None):
    if scan_id is None:
        flash('Invalid scan')
        return redirect(url_for('index'))

    studies = current_user.get_studies()
    scan = Scan.query.get(scan_id)
    if not current_user.has_study_access(scan.session.study):
        flash('Not authorised')
        return redirect(url_for('index'))

    form = ScanForm()
    if form.validate_on_submit():
        scan.bl_comment = form.bl_comment.data
        try:
            db.session.add(scan)
            db.session.commit()
            flash("Blacklist updated")
        except SQLAlchemyError as err:
            logger.error('Scan blacklist update failed:{}'.format(str(err)))
            flash('Update failed, admins have been notified, please try again')

    return render_template('scan.html',
                           studies=studies,
                           scan=scan,
                           form=form)


@app.route('/study')
@app.route('/study/<int:study_id>', methods=['GET', 'POST'])
@app.route('/study/<int:study_id>/<active_tab>', methods=['GET', 'POST'])
@login_required
def study(study_id=None, active_tab=None):
    if study_id is None:
        return redirect('/index')

    study = Study.query.get(study_id)

    if not current_user.has_study_access(study):
        flash('Not authorised')
        return redirect(url_for('index'))

    form = StudyOverviewForm()

    # load the study config
    cfg = dm.config.config()
    try:
        cfg.set_study(study.nickname)
    except KeyError:
        abort(500)

    readme_path = os.path.join(cfg.get_study_base(), 'README.md')

    try:
        with codecs.open(readme_path, encoding='utf-8', mode='r') as myfile:
            data = myfile.read()
    except IOError:
        data = ''

    if form.validate_on_submit():
        # form has been submitted check for changes
        # simple MD seems to replace \n with \r\n
        form.readme_txt.data = form.readme_txt.data.replace('\r', '')

        # also strip blank lines at the start and end as these are
        # automatically stripped when the form is submitted
        if not form.readme_txt.data.strip() == data.strip():
            # form has been updated so make a backup anf write back to file
            timestamp = datetime.datetime.now().strftime('%Y%m%d%H%m')
            base, ext = os.path.splitext(readme_path)
            backup_file = base + '_' + timestamp + ext
            try:
                shutil.copyfile(readme_path, backup_file)
            except (IOError, os.error, shutil.Error), why:
                logger.error('Failed to backup readme for study {} with excuse {}'
                             .format(study.nickname, why))
                abort(500)

            with codecs.open(readme_path, encoding='utf-8', mode='w') as myfile:
                myfile.write(form.readme_txt.data)
            data = form.readme_txt.data

    form.readme_txt.data = data
    form.study_id.data = study_id

    return render_template('study.html',
                           studies=current_user.get_studies(),
                           metricnames=study.get_valid_metric_names(),
                           study=study,
                           form=form,
                           active_tab=active_tab)


@app.route('/person')
@app.route('/person/<int:person_id>', methods=['GET'])
@login_required
def person(person_id=None):
    return redirect('/index')


@app.route('/metricData', methods=['GET', 'POST'])
@login_required
def metricData():
    form = SelectMetricsForm()
    data = None
    csv_data = None
    # Need to add a query_complete flag to the form

    if form.query_complete.data == 'True':
        data = metricDataAsJson()
        # Need the data field of the response object (data.data)
        temp_data = json.loads(data.data)["data"]
        if temp_data:
            csv_data = io.BytesIO()
            csvwriter = csv.writer(csv_data)
            csvwriter.writerow(temp_data[0].keys())
            for row in temp_data:
                csvwriter.writerow(row.values())


    if any([form.study_id.data,
            form.site_id.data,
            form.scantype_id.data,
            form.metrictype_id.data]):
        form_vals = query_metric_types(studies=form.study_id.data,
                                       sites=form.site_id.data,
                                       scantypes=form.scantype_id.data,
                                       metrictypes=form.metrictype_id.data)
    else:
        form_vals = query_metric_types()

    study_vals = []
    site_vals = []
    scantype_vals = []
    metrictype_vals = []

    for res in form_vals:
        study_vals.append((res[0].id, res[0].name))
        site_vals.append((res[1].id, res[1].name))
        scantype_vals.append((res[2].id, res[2].name))
        metrictype_vals.append((res[3].id, res[3].name))
        # study_vals.append((res.id, res.name))
        # for site in res.sites:
        #     site_vals.append((site.id, site.name))
        # for scantype in res.scantypes:
        #     scantype_vals.append((scantype.id, scantype.name))
        #     for metrictype in scantype.metrictypes:
        #         metrictype_vals.append((metrictype.id, metrictype.name))

    #sort the values alphabetically
    study_vals = sorted(set(study_vals), key=lambda v: v[1])
    site_vals = sorted(set(site_vals), key=lambda v: v[1])
    scantype_vals = sorted(set(scantype_vals), key=lambda v: v[1])
    metrictype_vals = sorted(set(metrictype_vals), key=lambda v: v[1])

    form.study_id.choices = study_vals
    form.site_id.choices = site_vals
    form.scantype_id.choices = scantype_vals
    form.metrictype_id.choices = metrictype_vals

    if csv_data:
        csv_data.seek(0)
        return render_template('getMetricData.html', form=form, data=csv_data.readlines())
    else:
        return render_template('getMetricData.html', form=form, data="")

def _checkRequest(request, key):
    # Checks a post request, returns none if key doesn't exist
    try:
        return(request.form.getlist(key))
    except KeyError:
        return(None)


@app.route('/metricDataAsJson', methods=['Get', 'Post'])
@login_required
def metricDataAsJson(format='http'):
    fields = {'studies': 'study_id',
              'sites': 'site_id',
              'sessions': 'session_id',
              'scans': 'scan_id',
              'scantypes': 'scantype_id',
              'metrictypes': 'metrictype_id'}

    byname = False # switcher to allow getting values byname instead of id

    try:
        if request.method == 'POST':
            byname = request.form['byname']
        else:
            byname = request.args.get('byname')
    except KeyError:
        pass


    for k, v in fields.iteritems():
        if request.method == 'POST':
            fields[k] = _checkRequest(request, v)
        else:
            if request.args.get(k):
                fields[k] = [x.strip() for x in request.args.get(k).split(',')]
            else:
                fields[k] = None

    # remove None values from the dict
    fields = dict((k, v) for k, v in fields.iteritems() if v)

    if byname:
        data = query_metric_values_byname(**fields)
    else:
        # convert from strings to integers
        for k, vals in fields.iteritems():
            try:
                fields[k] = int(vals)
            except TypeError:
                fields[k] = [int(v) for v in vals]

        data = query_metric_values_byid(**fields)

    objects = []
    for m in data:
        metricValue = m
        objects.append({'value':            metricValue.value,
                        'metrictype':       metricValue.metrictype.name,
                        'metrictype_id':    metricValue.metrictype_id,
                        'scan_id':          metricValue.scan_id,
                        'scan_name':        metricValue.scan.name,
                        'scan_description': metricValue.scan.description,
                        'scantype':         metricValue.scan.scantype.name,
                        'scantype_id':      metricValue.scan.scantype_id,
                        'session_id':       metricValue.scan.session_id,
                        'session_name':     metricValue.scan.session.name,
                        #'session_date':     metricValue.scan.session.date,
                        'site_id':          metricValue.scan.session.site_id,
                        'site_name':        metricValue.scan.session.site.name,
                        'study_id':         metricValue.scan.session.study_id,
                        'study_name':       metricValue.scan.session.study.name})

    if format == 'http':
        return(jsonify({'data': objects}))
    else:
        return(json.dumps(objects, indent=4, separators=(',', ': ')))


@app.route('/todo')
@app.route('/todo/<int:study_id>', methods=['GET'])
@login_required
def todo(study_id=None):
    if study_id:
        study = Study.query.get(study_id)
        study_name = study.nickname
    else:
        study_name = None

    if not current_user.has_study_access(study_id):
        flash('Not authorised')
        return redirect(url_for('index'))

    # todo_list = utils.get_todo(study_name)
    try:
        todo_list = utils.get_todo(study_name)
    except utils.TimeoutError:
        # should do something nicer here
        todo_list = {'error': 'timeout'}
    except RuntimeError as e:
        todo_list = {'error': 'runtime:{}'.format(e)}
    except:
        todo_list = {'error': 'other'}

    return jsonify(todo_list)


@app.route('/redcap', methods=['GET', 'POST'])
def redcap():
    logger.info('Recieved a query from redcap')
    if request.method == 'POST':
        logger.info('REDCAP method was POST')
        logger.info('POST fields were:{}'.format(request.form.keys()))
    else:
        logger.info('REDCAP method was GET')
        logger.info('GET fields were:{}'.format(request.args))
    return render_template('200.html'), 200


@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500


@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/authorize/<provider>')
def oauth_authorize(provider):
    if not current_user.is_anonymous:
        return redirect(url_for('login'))
    oauth = OAuthSignIn.get_provider(provider)
    return oauth.authorize()


@app.route('/callback/<provider>')
def oauth_callback(provider):
    if not current_user.is_anonymous:
        return redirect(url_for('index'))
    oauth = OAuthSignIn.get_provider(provider)
    access_token, github_user = oauth.callback()

    if access_token is None:
        flash('Authentication failed.')
        return redirect(url_for('login'))

    if provider == 'github':
        username = github_user['login']
    elif provider == 'gitlab':
        username = github_user['username']

    user = User.query.filter_by(username=username).first()
    if not user:
        username = User.make_unique_nickname(username)
        user = User(username=username,
                    realname=github_user['name'],
                    email=github_user['email'])
        db.session.add(user)
        db.session.commit()

    login_user(user, remember=True)
    flask_session['active_token'] = access_token
    return redirect(url_for('index'))
