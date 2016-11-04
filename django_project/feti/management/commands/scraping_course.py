import re
import urllib
import time
from urllib.error import HTTPError, URLError
from django.core.management.base import BaseCommand
from feti.models.course import Course
from feti.models.campus import Campus
from feti.models.provider import Provider
from feti.models.field_of_study import FieldOfStudy
from feti.models.national_qualifications_framework import NationalQualificationsFramework
from feti.models.education_training_quality_assurance import EducationTrainingQualityAssurance
from feti.utils import beautify, cleaning, get_soup, save_html, get_raw_soup, open_saved_html
from feti.management.commands.scraping_campus import scrape_campus

__author__ = 'Irwan Fathurrahman <irwan@kartoza.com>'
__date__ = '15/09/16'
__license__ = "GPL"
__copyright__ = 'kartoza.com'


def create_course(data):
    # save to database
    # provider
    if "ID" in data:
        data['id'] = data['ID']

    if "id" in data:
        print(("insert to database : %s" % data).encode('utf-8'))
        # getting education_training_quality_assurance
        education_training_quality_assurance = None
        if 'primary or delegated qa functionary' in data:
            edu_data = data['primary or delegated qa functionary'].split("-")
            if len(edu_data) == 2 and len(edu_data[0]) <= 30:
                try:
                    education_training_quality_assurance = EducationTrainingQualityAssurance.objects.get(
                        acronym=edu_data[0].strip())
                except EducationTrainingQualityAssurance.DoesNotExist:
                    education_training_quality_assurance = EducationTrainingQualityAssurance()
                    education_training_quality_assurance.acronym = edu_data[0].strip()
                    education_training_quality_assurance.body_name = edu_data[1].strip()
                    education_training_quality_assurance.save()
        # get NQF
        nqf = None
        if "TBA" not in data['nqf level'] and "N/A:" not in data['nqf level']:
            data['nqf level'] = data['nqf level'].split(" ")[2]
            try:
                nqf = NationalQualificationsFramework.objects.get(level=int(data['nqf level']))
            except NationalQualificationsFramework.DoesNotExist:
                nqf = None

        # get FOF
        field = data['field'].replace("0", "").split("-")
        field[0] = cleaning(field[0])
        field_class = int(field[0].split(" ")[1])
        try:
            fof = FieldOfStudy.objects.get(field_of_study_class=field_class)
        except FieldOfStudy.DoesNotExist:
            fof = FieldOfStudy()
            fof.field_of_study_class = field_class
            fof.field_of_study_description = field[1]
            fof.save()

        course = Course()
        course.education_training_quality_assurance = education_training_quality_assurance
        course.national_learners_records_database = int(data['id'])
        course.course_description = data['title']
        course.national_qualifications_framework = nqf
        course.field_of_study = fof
        course.save()
        return course


def parse_saqa_qualification_table(table):
    data = {}
    key_array = []
    value_array = []

    rows = table.findAll('tr')

    for idx, row in enumerate(rows):
        cols = row.findAll('td')
        for col in cols:
            if idx % 2:
                value_array.append(cleaning(col.get_text()))
            else:
                key_array.append(cleaning(col.get_text())
                                 .replace(" ", "_")
                                 .replace("-", "_")
                                 .lower())

    if len(key_array) == len(value_array):
        for i in range(len(key_array)):
            data[key_array[i]] = value_array[i]

    return data


def get_course_detail_from_saqa(qualification_id):
    # Get full detail of a course from SAQA
    # http://regqs.saqa.org.za/viewQualification.php?id=<qualification-id>

    saqa_detail = open_saved_html('saqa-course', qualification_id)

    if not saqa_detail:
        while True:
            try:
                saqa_detail = get_raw_soup(
                    'http://regqs.saqa.org.za/viewQualification.php?id=%s' % qualification_id
                )
                save_html('saqa-course', qualification_id, saqa_detail.content)
                saqa_detail = beautify(saqa_detail.content)
                break
            except HTTPError as detail:
                if detail.errno == 500:
                    time.sleep(1)
                    continue
                else:
                    raise

    if saqa_detail:
        tables = saqa_detail.findAll('table')
        processed_table = parse_saqa_qualification_table(tables[5])
        print(processed_table)


def scraping_course_ncap(start_page=0, max_page=0):
    # ----------------------------------------------------------
    # http://ncap.careerhelp.org.za/
    # ----------------------------------------------------------
    current_page = 1

    if start_page > 1:
        current_page = start_page

    if max_page < start_page:
        return

    print("GETTING COURSES FROM http://ncap.careerhelp.org.za/")
    print("----------------------------------------------------------")
    while True:
        print("processing page %d" % current_page)
        html = get_soup('http://ncap.careerhelp.org.za/qualifications/search/all/learningfield/all/'
                        'nqflevel/all/qualificationtype/all/page/%d' % current_page)
        items = html.findAll("div", {"class": "SearchResultItem"})
        for item in items:
            item_contents = item.text.split('\n')
            course_desc = item_contents[1].lstrip()

            if course_desc.find('No Courses Found') == 0:
                print('Finished scraping courses from saqa')
                return

            # Get saqa qualification id
            regexp = re.compile("SAQA Qualification ID : (.*)$")
            saqa_id = regexp.search(course_desc).group(1).split(',')[0]

            # Check if id already exist in db
            try:
                course = Course.objects.get(national_learners_records_database=saqa_id)
            except Course.DoesNotExist:
                # Open saqa qualification from id
                while True:
                    try:
                        saqa = get_soup('http://regqs.saqa.org.za/viewQualification.php?id=%s' % saqa_id)
                        break
                    except HTTPError as detail:
                        if detail.errno == 500:
                            time.sleep(1)
                            continue
                        else:
                            raise

                # Add course
                tables = saqa.findAll('table')
                if len(tables) == 0:
                    continue
                processed_table = parse_saqa_qualification_table(tables[5])
                course = create_course(processed_table)

            # Update campus
            try:
                campus_name = item_contents[2].split('-')[1]
            except IndexError:
                campus_name = ""
            primary_institution = item_contents[2].split('-')[0]

            try:
                provider = Provider.objects.get(
                    primary_institution=primary_institution)
                campus = Campus.objects.get(
                    campus=campus_name, provider=provider)
            except (Campus.DoesNotExist, Provider.DoesNotExist) as e:
                # create campus
                scrape_campus(item)
                provider = Provider.objects.get(
                    primary_institution=primary_institution)
                campus = Campus.objects.get(
                    campus=campus_name, provider=provider)

            campus.courses.add(course)
            campus.save()

        current_page += 1
        if current_page > max_page > 0:
            break
    print("----------------------------------------------------------")


def scraping_course_saqa():
    # ----------------------------------------------------------
    # http://regqs.saqa.org.za/search.php
    # ----------------------------------------------------------
    trying = 0
    increment = 20
    search_result_at_first = 0
    while True:
        print("----------------------------------------------------------")
        print("GETTING COURSE IN http://regqs.saqa.org.za/search.php/")
        print("----------------------------------------------------------")
        url = 'http://regqs.saqa.org.za/search.php'
        values = {"GO": "Go", "searchResultsATfirst": search_result_at_first,
                  "cat": "qual", "view": "list", "QUALIFICATION_TITLE": "",
                  "QUALIFICATION_ID": "", "NQF_LEVEL_ID": "", "NQF_LEVEL_G2_ID": "", "ABET_BAND_ID": "",
                  "SUBFIELD_ID": "", "QUALIFICATION_TYPE_ID": "", "ORIGINATOR_ID": "", "FIELD_ID": "",
                  "ETQA_ID": "",
                  "SEARCH_TEXT": "", "ACCRED_PROVIDER_ID": "", "NQF_SUBFRAMEWORK_ID": "",}
        print("processing %d to %d" % (search_result_at_first, search_result_at_first + increment))
        data = urllib.parse.urlencode(values)
        data = data.encode('ascii')  # data should be bytes
        req = urllib.request.Request(url, data)
        try:
            with urllib.request.urlopen(req) as response:
                html_doc = response.read()
                html = beautify(html_doc)

                # check emptiness
                items = html.findAll("table")
                last_table = str(items[len(items) - 1])
                if not "Next" in last_table and not "Prev" in last_table:
                    print("it is empty")
                    break
                # extract courses
                rows = html.findAll('tr')
                course = {}
                for row in rows:
                    tds = row.findAll('td')
                    if len(tds) == 2 and tds[0].string != None:

                        key = str(tds[0].string).replace(":", "").strip().lower()
                        value = str(tds[1].a.string).strip().lower() if tds[1].a != None else str(
                            tds[1].string).strip()
                        course[key] = cleaning(value)

                        if "title" in tds[0].string.lower():
                            if "title" in course:
                                create_course(course)
            trying = 0
        except (HTTPError, URLError):
            print("connection error, trying again - %d" % trying)
            trying += 1

        if trying == 0 or trying >= 3:
            search_result_at_first += increment


class Command(BaseCommand):
    help = 'Scrapping the courses information'
    args = '<args>'

    def add_arguments(self, parser):
        parser.add_argument(
            '--id',
            dest='id',
            help='Qualification id'
        )
        parser.add_argument(
            '--re_cache',
            dest='re_cache',
            help='Update html cache'
        )

    def handle(self, *args, **options):

        if options['id']:
            get_course_detail_from_saqa(options['id'])
        else:
            scraping_course_ncap()
