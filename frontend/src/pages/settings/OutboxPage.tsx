import { portalApi } from '../../api/portal.ts'
import { OutboxBrowser } from '../../components/OutboxList.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { t } from '../../i18n/index.ts'

export function OutboxPage() {
  const org = useActiveOrg()
  return (
    <div className="card card-wide">
      <h2>{t('Postausgang')}</h2>
      <p className="muted small">
        {t('Alle Mails, die die Software im Namen von {name} versendet hat.', { name: org.name })}
      </p>
      <OutboxBrowser
        load={(query) => portalApi.outbox(org.id, query)}
        deps={[org.id]}
        attachmentUrl={(mail, index) => portalApi.outboxAttachmentUrl(org.id, mail, index)}
      />
    </div>
  )
}
