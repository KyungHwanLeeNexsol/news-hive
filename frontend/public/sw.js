// Service Worker for Web Push notifications
// NewsHive 알림 수신 및 클릭 처리

self.addEventListener('push', function(event) {
  // push 이벤트 데이터 파싱 (JSON 형태 기대)
  const data = event.data ? event.data.json() : {};
  const title = data.title || 'NewsHive';
  const options = {
    body: data.body || '',
    icon: '/favicon.ico',
    badge: '/favicon.ico',
    data: { url: data.url || '/' },
  };
  // 알림이 표시될 때까지 서비스 워커 활성 상태 유지
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function(event) {
  // 알림 닫기
  event.notification.close();
  // 알림의 url로 탭 열기 또는 포커스 이동
  event.waitUntil(
    clients.openWindow(event.notification.data.url)
  );
});
