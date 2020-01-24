from flask_wtf import FlaskForm
from wtforms import SubmitField, TextAreaField, TextField, BooleanField
from wtforms.validators import DataRequired


class EmptySessionForm(FlaskForm):
    comment = TextAreaField(
        'Explanation: ',
        id="missing_comment",
        validators=[DataRequired()],
        render_kw={
            'rows': 4,
            'cols': 50,
            'required': True,
            'placeholder': 'Please describe what happened to this session.',
            'maxlength': '2048'
        })


class IncidentalFindingsForm(FlaskForm):
    comment = TextAreaField(
        'Description: ',
        id='finding-description',
        validators=[DataRequired()],
        render_kw={
            'rows': 4,
            'cols': 65,
            'required': True,
            'placeholder': 'Please describe the finding'
        })
    submit = SubmitField('Submit')


class TimepointCommentsForm(FlaskForm):
    comment = TextAreaField(
        validators=[DataRequired()],
        render_kw={
            'rows': 5,
            'required': True,
            'placeholder': 'Add new comment'
        })
    submit = SubmitField('Submit')


class NewIssueForm(FlaskForm):
    title = TextField(
        "Title: ",
        validators=[DataRequired()],
        render_kw={'required': True})
    body = TextAreaField(
        "Body: ",
        validators=[DataRequired()],
        render_kw={
            'rows': 4,
            'cols': 65,
            'required': True,
            'placeholder': 'Enter issue here.'
        })
    submit = SubmitField('Create Issue')


class DataDeletionForm(FlaskForm):
    raw_data = BooleanField('Raw Data')
    database_records = BooleanField('Database Records')
