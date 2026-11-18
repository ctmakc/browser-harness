#!/usr/bin/env bash
# Проверка ночного режима Chrome владельца (18.11): днём крон-тест получает 75, таймеры стоят в окне 23–07.
set -u; bad=0
if [ "$(date +%H)" -ge 7 ] && [ "$(date +%H)" -lt 23 ]; then
  printf 'print(page_info())\n' | systemd-run --user --quiet --wait --pipe --collect -E BU_AGENT=test-cron /home/llm/.local/bin/browser-harness >/dev/null 2>&1; rc=$?
  echo "test-cron днём: код $rc"; [ $rc -eq 75 ] || bad=1
fi
for t in li-comments li-comments-measure li-grocery-invites li-guide-articles li-withdraw-old ohc-fb-warm threads-leads mmix-comment-dm messenger-crm linkedin-services-watch lead-social mmix-fb-want meta-monitor owner-social-li mmix-fb-rot-check mmix-ad-comments academl-comment-dm gsc-request-indexing ohc-fb-renew ck-fb-report-scrape osmozg-fb-calendar; do
  n=$(systemctl --user show $t.timer -p NextElapseUSecRealtime --value); h=$(date -d "$n" +%H 2>/dev/null || echo XX)
  if [ "$(systemctl --user is-active $t.timer)" = active ] && { [ "$h" -ge 23 ] || [ "$h" -lt 7 ]; } 2>/dev/null; then echo "OK  $t $n"; else echo "BAD $t $n"; bad=1; fi
done
exit $bad
