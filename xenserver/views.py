from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse

from xenserver.models import XenServer, XenVM, Template
from xenserver import forms, tasks, iputil

import hashlib
import uuid
import time
import random
import urlparse

from celery.task.control import revoke

@login_required
def index(request):
    servers = XenServer.objects.all()

    stacks = []

    for server in servers:
        vms = server.xenvm_set.all()

        used_memory = sum([vm.memory for vm in vms])
        mem_total = server.memory
        if not mem_total:
            # Prevent a divide by zero
            mem_total = 1 
        mem_util = (used_memory/float(mem_total))*100

        stacks.append({
            'hostname': server.hostname,
            'vms': vms, 
            'mem_util': mem_util,
            'mem_total': mem_total,
            'mem_used': used_memory
        })

    return render(request, "index.html", {
        'servers': stacks
    })

@login_required
def accounts_profile(request):
    if request.method == "POST":
        form = forms.UserForm(request.POST, instance=request.user)

        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            return redirect('home')
    else:
        form = forms.UserForm(instance=request.user)

    return render(request, "accounts_profile.html", {
        'form': form
    })

@login_required
def template_index(request):

    templates = Template.objects.all()

    return render(request, "templates/index.html", {
        'templates': templates
    })

@login_required
def template_create(request):
    if not request.user.is_superuser:
        return redirect('template_index')

    if request.method == "POST":
        form = forms.TemplateForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            template.save()
            return redirect('template_index')

    else:
        form = forms.TemplateForm()

    return render(request, 'templates/create_edit.html', {
        'form': form
    })

@login_required
def template_edit(request, id):
    if not request.user.is_superuser:
        return redirect('home')

    template = Template.objects.get(id=id)
    if request.method == "POST":
        form = forms.TemplateForm(request.POST, instance=template)

        if form.is_valid():
            template = form.save(commit=False)
            template.save()

            return redirect('template_index')

    else:
        form = forms.TemplateForm(instance=template)
    d = {
        'form': form, 
        'template': template
    }

    return render(request, 'templates/create_edit.html', d)

@login_required
def server_index(request):
    servers = XenServer.objects.all()
    
    return render(request, "servers/index.html", {
        'servers': servers
    })

@login_required
def server_view(request, id):
    server = XenServer.objects.get(id=id)

    vms = server.xenvm_set.all()
    used_addresses = [vm.ip for vm in vms if vm.ip]

    return render(request, 'servers/view.html', {
        'server': server, 
        'vms': vms, 
    })

@login_required
def server_create(request):
    if not request.user.is_superuser:
        return redirect('server_index')

    if request.method == "POST":
        form = forms.XenServerForm(request.POST)
        if form.is_valid():
            server = form.save(commit=False)
            server.save()
            return redirect('server_index')

    else:
        form = forms.XenServerForm()

    return render(request, 'servers/create_edit.html', {
        'form': form
    })

@login_required
def server_edit(request, id):
    if not request.user.is_superuser:
        return redirect('home')

    server = XenServer.objects.get(id=id)
    if request.method == "POST":
        form = forms.XenServerForm(request.POST, instance=server)

        if form.is_valid():
            server = form.save(commit=False)
            server.save()

            return redirect('server_index')

    else:
        form = forms.XenServerForm(instance=server)
    d = {
        'form': form, 
        'server': server
    }

    return render(request, 'servers/create_edit.html', d)

@login_required
def terminate(request, id):
    if not request.user.is_superuser:
        return redirect('home')

    vm = XenVM.objects.get(id=id)

    if vm.xsref:
        tasks.destroy_vm.delay(vm)

        vm.status = 'Terminating'

    return redirect('home')

@login_required
def provision(request):
    if request.method == "POST":
        form = forms.ProvisionForm(request.POST)
        if form.is_valid():
            provision = form.cleaned_data
            server = provision['server']
            template = provision['template']
            hostname = provision['hostname']
            host, domain = hostname.split('.', 1)

            # Find the first free IP address
            vms = server.xenvm_set.all()
            used_addresses = [vm.ip for vm in vms if vm.ip]

            ip = iputil.firstRemaining(server.subnet, used_addresses)
            gateway = iputil.getGateway(server.subnet)
            netmask = iputil.getNetmask(server.subnet)

            # Get a preseed URL
            url = urlparse.urljoin(request.build_absolute_uri(),
                reverse('get_preseed', kwargs={'id':template.id}))

            vmobj = XenVM.objects.create(
                xsref='',
                name=name,
                status='Provisioning',
                sockets=template.cores,
                memory=template.memory,
                xenserver=server,
                ip=ip
            )
            vmobj.save()

            # Send provisioning to celery
            task = tasks.create_vm.delay(
                server, template, host, domain, ip, netmask, gateway, url)

            return redirect('home')
    else:
        form = forms.ProvisionForm()

    return render(request, 'provision.html', {
        'form': form
    })

def get_preseed(request, id):
    template = Template.objects.get(id=id)

    return HttpResponse(template.preseed, content_type="text/plain")
