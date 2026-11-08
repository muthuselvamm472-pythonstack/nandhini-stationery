// Nandhini Stationery Service Worker (Background & Offline Push Engine)
const CACHE_NAME = 'nandhini-sw-v1';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

// Real-Time Web Push Event (Triggered even when browser tab is closed)
self.addEventListener('push', function(event) {
    let payload = {
        title: 'Nandhini Stationery (நந்தினி ஸ்டேஷனரி)',
        message: 'New reward milestone or stationery offer available!',
        haptic: 'celebration',
        url: '/dashboard/'
    };

    if (event.data) {
        try {
            payload = event.data.json();
        } catch (e) {
            payload.message = event.data.text();
        }
    }

    const vibrationPattern = payload.haptic === 'celebration'
        ? [120, 60, 120, 60, 250]
        : [80, 50, 160];

    const targetUrl = new URL(payload.url || '/dashboard/', self.location.origin).href;

    const options = {
        body: payload.message || 'Check your loyalty points & free gifts!',
        icon: 'https://cdn-icons-png.flaticon.com/512/2921/2921222.png',
        badge: 'https://cdn-icons-png.flaticon.com/512/2921/2921222.png',
        vibrate: vibrationPattern,
        tag: 'nandhini-broadcast',
        renotify: true,
        requireInteraction: true,
        data: {
            url: targetUrl,
            timestamp: Date.now()
        },
        actions: [
            { action: 'open_dashboard', title: '🎁 Open Rewards' },
            { action: 'dismiss', title: 'Dismiss' }
        ]
    };

    event.waitUntil(
        self.registration.showNotification(payload.title || 'Nandhini Stationery', options)
    );
});

// Notification Click Handler (Focuses existing tab or opens new window)
self.addEventListener('notificationclick', function(event) {
    event.notification.close();

    if (event.action === 'dismiss') {
        return;
    }

    const rawTarget = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/dashboard/';
    const targetUrl = new URL(rawTarget, self.location.origin).href;

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
            for (let i = 0; i < clientList.length; i++) {
                const client = clientList[i];
                if (client.url.includes(self.location.origin)) {
                    if ('focus' in client) {
                        client.focus();
                    }
                    if ('navigate' in client && !client.url.includes('/dashboard/')) {
                        return client.navigate(targetUrl);
                    }
                    return;
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});

// Message listener for in-page triggers
self.addEventListener('message', function(event) {
    if (event.data && event.data.type === 'SHOW_NOTIFICATION') {
        const d = event.data;
        const targetUrl = new URL(d.url || '/dashboard/', self.location.origin).href;
        const options = {
            body: d.message,
            icon: 'https://cdn-icons-png.flaticon.com/512/2921/2921222.png',
            badge: 'https://cdn-icons-png.flaticon.com/512/2921/2921222.png',
            vibrate: d.haptic === 'celebration' ? [120, 60, 120, 60, 250] : [80, 50, 160],
            tag: 'nandhini-broadcast',
            renotify: true,
            requireInteraction: true,
            data: { url: targetUrl }
        };
        self.registration.showNotification(d.title, options);
    }
});
