css = open('app/static/css/style.css', encoding='utf-8').read()
js  = open('app/static/js/timer.js',   encoding='utf-8').read()
html= open('app/templates/home.html',  encoding='utf-8').read()

checks = [
    ('CSS padding 42px 48px 36px 48px',    'padding: 42px 48px 36px 48px' in css),
    ('CSS min-height 240px',               'min-height: 240px' in css),
    ('CSS .pause-card::before',            '.pause-card::before' in css),
    ('CSS content attr(data-quadro)',      'attr(data-quadro)' in css),
    ('CSS .pause-card-right width 200px',  '  width: 200px' in css),
    ('CSS .pause-message font-size 46px',  'font-size: 46px' in css),
    ('CSS min-width 152px',                'min-width: 152px' in css),
    ('JS (function wireButtons',           '(function wireButtons' in js),
    ('JS card.dataset.quadro',             'card.dataset.quadro' in js),
    ('JS window.focoPauseDebug',           'window.focoPauseDebug' in js),
    ('HTML data-quadro',                   'data-quadro' in html),
    ('HTML id=protected-zone',             'id="protected-zone"' in html),
    ('HTML id=resting-wrapper',            'id="resting-wrapper"' in html),
]

all_ok = True
for label, ok in checks:
    status = 'OK  ' if ok else 'FAIL'
    print(status + ' | ' + label)
    if not ok:
        all_ok = False

print()
print('All checks passed!' if all_ok else 'SOME CHECKS FAILED!')
