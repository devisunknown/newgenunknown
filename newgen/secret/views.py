from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.conf import settings
from django.db.models import Count, Q, Subquery, OuterRef
from django.utils import timezone
import uuid
import hashlib
from .models import Leader, Conversation, Message, Anonymous


def _hash_string(value):
    if not value:
        return None
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _get_or_create_anonymous(request):
    
    anon_id = request.session.get('anon_id')
    anonymous = None

    if anon_id:
        anonymous = Anonymous.objects.filter(id=anon_id).first()  

    if anonymous is None:
        anonymous = Anonymous.objects.create(
            ip_hash=_hash_string(request.META.get('REMOTE_ADDR')),
            user_agent_hash=_hash_string(request.META.get('HTTP_USER_AGENT', ''))
        )
        request.session['anon_id'] = str(anonymous.id)

    return anonymous


def leader_directory(request):
    leaders = Leader.objects.all()
    return render(request, 'contact.html', {'leaders': leaders})


def stranger_inbox(request):
    anonymous = _get_or_create_anonymous(request)
    conversations = Conversation.objects.filter(anonymous=anonymous).select_related('leader').prefetch_related('messages')
    return render(request, 'stranger_inbox.html', {'conversations': conversations})


def chat_room(request, leader_id):
    leader = get_object_or_404(Leader, id=leader_id)
    anonymous = _get_or_create_anonymous(request)

    conv, created = Conversation.objects.get_or_create(
        leader=leader,
        anonymous=anonymous
    )

    messages = conv.messages.all()
    ws_scheme = 'wss' if request.is_secure() else 'ws'
    ws_url = f"{ws_scheme}://{request.get_host()}/ws/chat/{conv.id}/anon/"

    return render(request, 'message.html', {
        'leader': leader,
        'conversation': conv,
        'messages': messages,
        'ws_url': ws_url,
    })


@require_POST
def send_message(request, conv_id):
    conv = get_object_or_404(Conversation, id=conv_id)
    body = request.POST.get('body', '').strip()

    if not body:
        return JsonResponse({'error': 'Empty message'}, status=400)

    anon_id = request.session.get('anon_id')
    if anon_id and conv.anonymous_id and str(conv.anonymous.id) == anon_id:
        sender_type = 'anon'
        conv.anonymous.last_seen = timezone.now()
        conv.anonymous.save(update_fields=['last_seen'])
    else:
        sender_type = 'leader'

    msg = Message.objects.create(
        conversation=conv,
        sender_type=sender_type,
        body=body
    )

    return JsonResponse({
        'id': str(msg.id),
        'body': msg.body,
        'sender_type': msg.sender_type,
        'created_at': msg.created_at.strftime('%I:%M %p')
    })


def leader_signin(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        try:
            leader = Leader.objects.get(email=email)
            if leader.check_password(password):
                request.session['leader_id'] = str(leader.id)
                return redirect('leader_inbox')
            else:
                return render(request, 'sign_in.html', {'error': 'Invalid password'})
        except Leader.DoesNotExist:
            return render(request, 'sign_in.html', {'error': 'Leader not found'})

    return render(request, 'sign_in.html')


def leader_inbox(request):
    leader_id = request.session.get('leader_id')
    if not leader_id:
        return redirect('signin')

    leader = get_object_or_404(Leader, id=leader_id)
    conversations = leader.conversations.all().select_related('anonymous').prefetch_related('messages')

    last_message_subquery = Message.objects.filter(
        conversation=OuterRef('pk')
    ).order_by('-created_at').values('body', 'created_at')[:1]

    conversations = conversations.annotate(
        unread_count=Count('messages', filter=Q(messages__sender_type='anon', messages__is_read=False)),
        last_message_body=Subquery(last_message_subquery.values('body')[:1]),
        last_message_created_at=Subquery(last_message_subquery.values('created_at')[:1])
    )

    return render(request, 'leader_inbox.html', {
        'leader': leader,
        'conversations': conversations
    })


def leader_chat(request, conv_id):
    leader_id = request.session.get('leader_id')
    if not leader_id:
        return redirect('signin')

    leader = get_object_or_404(Leader, id=leader_id)
    conv = get_object_or_404(Conversation, id=conv_id, leader=leader)

    conv.messages.filter(sender_type='anon', is_read=False).update(is_read=True)

    ws_scheme = 'wss' if request.is_secure() else 'ws'
    ws_url = f"{ws_scheme}://{request.get_host()}/ws/chat/{conv.id}/leader/"

    return render(request, 'message.html', {
        'leader': leader,
        'conversation': conv,
        'messages': conv.messages.all(),
        'ws_url': ws_url,
    })


def leader_logout(request):
    request.session.flush()
    return redirect('signin')