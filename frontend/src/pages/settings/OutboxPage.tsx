import { portalApi } from '../../api/portal.ts'
import { OutboxBrowser } from '../../components/OutboxList.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'

export function OutboxPage() {
  const org = useActiveOrg()
  return (
    <div className="card card-wide">
      <h2>Postausgang</h2>
      <p className="muted small">
        Alle Mails, die die Software im Namen von {org.name} versendet hat.
      </p>
      <OutboxBrowser
        load={(query) => portalApi.outbox(org.id, query)}
        deps={[org.id]}
        attachmentUrl={(mail, index) => portalApi.outboxAttachmentUrl(org.id, mail, index)}
      />
    </div>
  )
}
