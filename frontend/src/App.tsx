import { Route, Routes } from 'react-router-dom';
import AppShell from './components/AppShell';
import { ToastProvider } from './components/Toast';
import { AppProvider } from './context/AppContext';
import ClusterPage from './pages/ClusterPage';
import MapPage from './pages/MapPage';
import NotFoundPage from './pages/NotFoundPage';
import ReportPage from './pages/ReportPage';
import ScorecardPage from './pages/ScorecardPage';

export default function App() {
  return (
    <ToastProvider>
      <AppProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<MapPage />} />
            <Route path="report" element={<ReportPage />} />
            <Route path="clusters/:id" element={<ClusterPage />} />
            <Route path="scorecard" element={<ScorecardPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </AppProvider>
    </ToastProvider>
  );
}
