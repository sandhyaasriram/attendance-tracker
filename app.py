from flask import Flask, render_template, request, redirect, jsonify
from pymongo import MongoClient

app = Flask(__name__)

client = MongoClient("mongodb://localhost:27017/")
db = client["attendance_db"]
students_collection = db["students"]

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        name = request.form['name']
        student_id = request.form['student_id']
        gpa = float(request.form['gpa'])
        num_courses = int(request.form['num_courses'])
        
        courses_data = []
        total_classes = 0
        total_attended = 0

        for i in range(1, num_courses + 1):
            course_name = request.form[f'course_{i}']
            total = int(request.form[f'total_classes_{i}'])
            attended = int(request.form[f'attended_classes_{i}'])
            
            attendance_percentage = (attended / total) * 100
            courses_data.append({
                'course': course_name,
                'total_classes': total,
                'attended_classes': attended,
                'attendance_percentage': attendance_percentage
            })
            
            total_classes += total
            total_attended += attended

        overall_attendance = (total_attended / total_classes) * 100 if total_classes > 0 else 0

        existing_student = students_collection.find_one({'student_id': student_id})
        if existing_student:
            students_collection.update_one(
                {'student_id': student_id},
                {'$set': {
                    'name': name,
                    'gpa': gpa,
                    'courses': courses_data,
                    'overall_attendance': overall_attendance
                }}
            )
        else:
            students_collection.insert_one({
                'student_id': student_id,
                'name': name,
                'gpa': gpa,
                'courses': courses_data,
                'overall_attendance': overall_attendance
            })

        return redirect('/')
    
    student_data = list(students_collection.find())

    summary = {}
    for student in student_data:
        sid = student['student_id']
        name = student['name']
        gpa = student['gpa']
        
        if not name.strip() or not sid.strip() or gpa < 0 or gpa > 10:
            return "Invalid input: Check name, student ID, or GPA.", 400


        overall_attendance = student.get('overall_attendance', 0)
        courses = student.get('courses', [])

        if len(courses) < 1 or len(courses) > 15:
            return "Invalid number of courses.", 400

        for course in courses:
            course_name = course['course']
            total = course['total_classes']
            attended = course['attended_classes']
            
            if not course_name.strip() or total <= 0 or attended < 0 or attended > total:
                return "Invalid course data: check course names and class values", 400

        summary[sid] = {
            'student_id': sid,
            'name': name,
            'gpa': gpa,
            'overall_attendance': overall_attendance,
            'courses': courses
        }

    return render_template('index.html', students=summary, has_students=bool(student_data))

@app.route('/delete_backend/<student_id>', methods=['GET'])
def delete_backend(student_id):
    result = students_collection.delete_one({'student_id': student_id})
    
    if result.deleted_count > 0:
        return redirect('/') 
    else:
        return f"No student found with student_id {student_id}.", 404

@app.route('/edit/<student_id>', methods=['GET'])
def edit_page(student_id):
    student = students_collection.find_one({'student_id': student_id})
    if not student:
        return "Student not found.", 404
    return render_template('edit.html', student=student)

@app.route('/edit/<student_id>', methods=['POST'])
def edit(student_id):
    name = request.form['name']
    gpa = float(request.form['gpa'])
    num_courses = int(request.form['num_courses'])

    courses_data = []
    total_attended = 0
    total_classes = 0

    for i in range(1, num_courses + 1):
        course_name = request.form[f'course_{i}']
        total = int(request.form[f'total_classes_{i}'])
        attended = int(request.form[f'attended_classes_{i}'])
        attendance_percentage = (attended / total) * 100

        courses_data.append({
            'course': course_name,
            'total_classes': total,
            'attended_classes': attended,
            'attendance_percentage': attendance_percentage
        })

        total_attended += attended
        total_classes += total

    overall_attendance = (total_attended / total_classes) * 100 if total_classes > 0 else 0

    students_collection.update_one(
        {'student_id': student_id},
        {'$set': {
            'name': name,
            'gpa': gpa,
            'courses': courses_data,
            'overall_attendance': overall_attendance
        }}
    )

    return redirect('/')

@app.route('/calculate_skips/<student_id>/<goal>')
def calculate_skips(student_id, goal):
    student = students_collection.find_one({'student_id': student_id})
    if not student:
        return jsonify({'error': 'Student not found'}), 404

    gpa     = student['gpa']
    courses = student['courses']
    # original totals
    total_attended = sum(c['attended_classes'] for c in courses)
    total_classes  = sum(c['total_classes']  for c in courses)

    # set targets
    overall_target = 0.75 if goal == '75' else 0.85
    if goal == '75':
        individual_target = 0.75 if gpa < 9 else 0.35
    else:
        individual_target = 0.75

    # prepare round-robin skipping
    skips = {c['course']: 0 for c in courses}
    active = [c['course'] for c in courses]

    # map course-name → its original counts
    orig = {c['course']: (c['attended_classes'], c['total_classes']) for c in courses}

    # keep looping until none can be bumped
    while active:
        removed = []
        for name in active:
            att, tot = orig[name]
            # propose one more skip for this course
            proposed = skips[name] + 1
            # build new totals for this course
            new_course_total = tot + proposed
            # overall totals if we applied all current skips + this one
            total_skipped = sum(skips.values()) + 1
            new_overall_total   = total_classes + total_skipped
            new_overall_attend  = total_attended

            # compute percentages
            pct_course  = att / new_course_total
            pct_overall = new_overall_attend / new_overall_total

            # if both constraints still hold, commit the skip
            if pct_course >= individual_target and pct_overall >= overall_target:
                skips[name] = proposed
            else:
                # otherwise retire this course from further skipping
                removed.append(name)

        for name in removed:
            active.remove(name)

    # format result
    display = []
    for course in courses:
        name = course['course']
        sessions = skips[name]
        # if it’s a lab, two class‐sessions = one lab session
        if 'LAB' in name.upper():
            units = sessions // 2
        else:
            units = sessions
        display.append({
            'course':   name,
            'can_skip': units
        })

    return jsonify(display)

if __name__ == '__main__':
    app.run(debug=True)
