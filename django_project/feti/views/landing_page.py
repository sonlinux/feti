# coding=utf-8
"""FETI landing page view."""
from haystack.inputs import AutoQuery

__author__ = 'Christian Christelis <christian@kartoza.com>'
__date__ = '04/2015'
__license__ = "GPL"
__copyright__ = 'kartoza.com'

from collections import OrderedDict
from haystack.query import SearchQuerySet

from django.shortcuts import render
from django.http import HttpResponse
from django.template import RequestContext

from feti.models.campus import Campus
from feti.models.course import Course


def update_course_dict(campus_dict, campus, course):
    if campus not in campus_dict:
        campus_dict[campus] = [course]
    else:
        if course not in campus_dict[campus]:
            campus_dict[campus].append(course)


def update_campus_dict(provider_dict, provider, campus):
    if provider not in provider_dict:
        campus_dict = dict()
        campus_dict[campus] = []
        provider_dict[provider] = campus_dict
    else:
        if campus not in provider_dict[provider]:
            provider_dict[provider][campus] = []

def landing_page(request):
    """Serves the FETI landing page.

    :param request: A django request object.
    :type request: request

    :returns: Returns the landing page.
    :rtype: HttpResponse
    """
    # sort the campus alphabetically
    def provider_key(item):
        return item[0].primary_institution.strip().lower()

    search_terms = ''
    provider_dict = OrderedDict()
    errors = None
    if request.GET:
        search_terms = request.GET.get('search_terms')
        if search_terms:

            results = SearchQuerySet().filter(
                long_description=AutoQuery(search_terms)).models(Campus,
                                                                 Course)
            campuses = []

            for result in results:
                if result.score > 1:
                    # get model
                    model = result.model
                    # get objects
                    object_instance = result.object
                    # if we got campus model
                    if model == Campus and isinstance(object_instance, Campus):
                        campus = object_instance
                        if campus.incomplete:
                            continue
                        if campus not in campuses:
                            campuses.append(campus)
                        provider = campus.provider
                        update_campus_dict(provider_dict, provider, campus)
                        for course in campus.courses.all():
                            update_course_dict(
                                provider_dict[provider], campus, course)
                    if model == Course and isinstance(object_instance, Course):
                        course = object_instance
                        for campus in course.campus_set.all():
                            if campus.incomplete:
                                continue
                            if campus not in campuses:
                                campuses.append(campus)
                            provider = campus.provider
                            update_campus_dict(provider_dict, provider, campus)
                            update_course_dict(
                                provider_dict[provider], campus, course)

    if not request.GET or not search_terms:
        campuses = Campus.objects.filter(_complete=True).order_by(
            '_long_description')
        for campus in campuses:
            if campus.incomplete:
                continue
            provider = campus.provider
            update_campus_dict(provider_dict, provider, campus)
            for course in campus.courses.all():
                update_course_dict(provider_dict[provider], campus, course)

    provider_dict = OrderedDict(
        sorted(provider_dict.items(), key=provider_key))

    context = {
        'campuses': campuses,
        'provider_dict': provider_dict,
        'search_terms': search_terms,
        'errors': errors
    }
    return render(
        request,
        'feti/feti.html',
        context_instance=RequestContext(request, context))
