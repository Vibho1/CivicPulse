import { Link } from 'react-router-dom';
import { EmptyState } from '../components/ui';

export default function NotFoundPage() {
  return (
    <div className="page narrow">
      <div className="card">
        <EmptyState title="Page not found" body="That link doesn't go anywhere. Head back to the live map." icon="map">
          <Link to="/" className="btn btn-primary">
            Back to map
          </Link>
        </EmptyState>
      </div>
    </div>
  );
}
