# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from io import BytesIO
import pandas as pd
from sqlalchemy.sql import func

app = Flask(__name__)
app.config['SECRET_KEY'] = 'yoursecretkeyhere'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.db'
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)

    def get_id(self):
        return self.username

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    date = db.Column(db.Date, default=lambda: datetime.now(timezone.utc).date())
    time_in = db.Column(db.Time, default=lambda: datetime.now(timezone.utc).time())
    time_out = db.Column(db.Time, nullable=True)

class Break(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False)
    date = db.Column(db.Date, default=lambda: datetime.now(timezone.utc).date())
    break_start = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    break_end = db.Column(db.DateTime, nullable=True)

@login_manager.user_loader
def load_user(username):
    return User.query.filter_by(username=username).first()
@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            if user.username == 'admin':
                return redirect(url_for('admin'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')
@app.route('/punch_out')
@login_required
def punch_out():
    today = datetime.now(timezone.utc).date()
    record = Attendance.query.filter_by(username=current_user.username, date=today).first()
    if record:
        record.time_out = datetime.now(timezone.utc).time()
        db.session.commit()
    logout_user()
    flash("You have successfully punched out and been logged out.", "info")
    return redirect(url_for('login'))


@app.route('/mark_attendance')
@login_required
def mark_attendance():
    now = datetime.now(timezone.utc)
    today = now.date()
    allowed_start = now.replace(hour=13, minute=0, second=0, microsecond=0)
    allowed_end = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now.hour < 7:
        allowed_start = allowed_start.replace(day=allowed_start.day - 1)
    if Attendance.query.filter_by(username=current_user.username, date=today).first():
        flash("Attendance already marked for today.", "info")
    else:
        record = Attendance(username=current_user.username, timestamp=now, date=today, time_in=now.time())
        db.session.add(record)
        db.session.commit()
        flash(f"Welcome {current_user.username}, Your attendance marked successfully", "success")
    return redirect(url_for('dashboard'))

@app.route('/punch_out')
@login_required
def punch_out():
    today = datetime.now(timezone.utc).date()
    record = Attendance.query.filter_by(username=current_user.username, date=today).first()
    if record:
        record.time_out = datetime.now(timezone.utc).time()
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/start_break')
@login_required
def start_break():
    br = Break(username=current_user.username)
    db.session.add(br)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/end_break')
@login_required
def end_break():
    latest_break = Break.query.filter_by(username=current_user.username, break_end=None).order_by(Break.break_start.desc()).first()
    if latest_break:
        latest_break.break_end = datetime.now(timezone.utc)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.username == 'admin':
        return redirect(url_for('admin'))

    today = datetime.now().date()
    present_days = [
        a.date.day
        for a in Attendance.query.filter_by(username=current_user.username).all()
        if a.date.month == today.month
    ]

    return render_template('dashboard.html', present_days=present_days)


@app.route('/admin')
@login_required
def admin():
    if current_user.username != 'admin':
        return "Unauthorized Access", 403

    total_users = User.query.count()
    total_attendance = Attendance.query.count()
    total_breaks = Break.query.count()
    attendance_records = Attendance.query.order_by(Attendance.timestamp.desc()).all()

    break_summary = db.session.query(
        Break.username,
        func.sum(func.strftime('%s', Break.break_end) - func.strftime('%s', Break.break_start)).label('total_seconds')
    ).filter(Break.break_end.isnot(None)).group_by(Break.username).all()

    break_summary = [
        {
            'username': row[0],
            'total_duration': str(datetime.utcfromtimestamp(row[1]).strftime('%H:%M:%S')) if row[1] else '00:00:00'
        } for row in break_summary
    ]

    users = User.query.all()

    today = datetime.now(timezone.utc).date()
    attendance_summary = {}
    records_today = Attendance.query.filter(Attendance.date == today).all()
    for r in records_today:
        attendance_summary[r.username] = attendance_summary.get(r.username, 0) + 1

    break_summary_today = {}
    breaks_today = Break.query.filter(func.date(Break.break_start) == today, Break.break_end.isnot(None)).all()
    for b in breaks_today:
        duration = (b.break_end - b.break_start).total_seconds() / 60
        break_summary_today[b.username] = break_summary_today.get(b.username, 0) + round(duration, 1)

    return render_template(
        'admin.html',
        total_users=total_users,
        total_attendance=total_attendance,
        total_breaks=total_breaks,
        attendance_records=attendance_records,
        break_summary=break_summary,
        users=users,
        attendance_summary=attendance_summary,
        break_summary_today=break_summary_today
    )

@app.route('/admin/add_user', methods=['POST'])
@login_required
def add_user():
    if current_user.username != 'admin':
        return "Unauthorized Access", 403

    username = request.form['username']
    password = request.form['password']
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        return render_template('admin.html', error="Username already exists")

    hashed_password = generate_password_hash(password)
    new_user = User(username=username, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()

    return redirect(url_for('admin'))

@app.route('/admin/reset_password/<username>', methods=['GET', 'POST'])
@login_required
def reset_password(username):
    if current_user.username != 'admin':
        return "Unauthorized Access", 403

    user = User.query.filter_by(username=username).first_or_404()
    if request.method == 'POST':
        new_password = request.form['new_password']
        hashed_password = generate_password_hash(new_password)
        user.password = hashed_password
        db.session.commit()
        flash(f"Password for {username} has been reset successfully!", "success")
        return redirect(url_for('admin'))

    return render_template('reset_password.html', user=user)

@app.route('/export/attendance')
@login_required
def export_attendance():
    if current_user.username != 'admin':
        return "Unauthorized Access", 403

    records = Attendance.query.order_by(Attendance.timestamp.desc()).all()
    data = [{'Username': r.username, 'Date': r.date, 'Time In': r.time_in, 'Time Out': r.time_out} for r in records]
    df = pd.DataFrame(data)

    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name='attendance_report.xlsx', as_attachment=True)

@app.route('/export/breaks')
@login_required
def export_breaks():
    if current_user.username != 'admin':
        return "Unauthorized Access", 403

    breaks = Break.query.order_by(Break.id.desc()).all()
    data = [{'Username': b.username, 'Break Start': b.break_start, 'Break End': b.break_end} for b in breaks]
    df = pd.DataFrame(data)

    output = BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(output, download_name='breaks_report.xlsx', as_attachment=True)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
