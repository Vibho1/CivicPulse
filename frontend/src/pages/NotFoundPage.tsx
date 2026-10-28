import { Link } from 'react-router-dom';
import { EmptyState } from '../components/ui';
import { useI18n } from '../i18n';

export default function NotFoundPage() {
  const { t } = useI18n();
  return (
    <div className="page narrow">
      <div className="card">
        <EmptyState title={t('notFound.title')} body={t('notFound.body')} icon="map">
          <Link to="/" className="btn btn-primary">
            {t('common.backToMap')}
          </Link>
        </EmptyState>
      </div>
    </div>
  );
}
