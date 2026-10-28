import { LANGS, useI18n, type Lang } from './index';

/** Each language is named in its own script, so it can be found whatever the current UI language. */
const SHORT: Record<Lang, string> = { en: 'EN', kn: 'ಕನ್ನಡ' };
const NAME: Record<Lang, string> = { en: 'English', kn: 'ಕನ್ನಡ' };

/**
 * Segmented EN | ಕನ್ನಡ switch built on the existing `.btn .btn-ghost .btn-sm` styles (extra rules
 * in i18n.css). In the app header on phones only the other language's button is shown, so the
 * control takes the room of one small button.
 */
export function LanguageToggle({ className }: { className?: string }) {
  const { lang, setLang, t } = useI18n();
  return (
    <div className={className ? `lang-toggle ${className}` : 'lang-toggle'} role="group" aria-label={t('lang.label')}>
      {LANGS.map((l) => {
        const active = l === lang;
        return (
          <button
            key={l}
            type="button"
            lang={l}
            className={`btn btn-ghost btn-sm lang-toggle-btn${active ? ' active' : ''}`}
            aria-pressed={active}
            title={active ? NAME[l] : t('lang.switchTo', { language: NAME[l] })}
            onClick={() => setLang(l)}
          >
            {SHORT[l]}
          </button>
        );
      })}
    </div>
  );
}

export default LanguageToggle;
