from django.urls import path
from stravakit import views


app_name = 'stravakit'

urlpatterns = [
    path('',              views.DashboardView.as_view(),  name='dashboard'),
    path('refresh/',      views.RefreshView.as_view(),  name='refresh'),
    path('oauth/connect/',  views.oauth_connect,   name='oauth_connect'),
    path('oauth/callback/', views.oauth_callback,  name='oauth_callback'),
    path('activity/<int:pk>/card/', views.ActivityCardView.as_view(),  name='activity_card'),
    path('activities/',   views.ActivitiesView.as_view(),  name='activities'),
    path('gear/',         views.GearView.as_view(),  name='gear'),
    path('gallery/',      views.GalleryView.as_view(),  name='gallery'),
    path('compare/',      views.CompareView.as_view(),  name='compare'),
]
