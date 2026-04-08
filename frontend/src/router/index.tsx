import { lazy, Suspense } from 'react';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';

const HomePage = lazy(() => import('../views/HomePage'));
const DemoPage = lazy(() => import('../views/DemoPage'));
const ProcessView = lazy(() => import('../views/ProcessView'));
const SimulationView = lazy(() => import('../views/SimulationView'));
const SimulationRunView = lazy(() => import('../views/SimulationRunView'));
const ReportView = lazy(() => import('../views/ReportView'));
const InteractionView = lazy(() => import('../views/InteractionView'));

function Loading() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
      <div className="glass-card" style={{ padding: '2rem 3rem' }}>
        <p style={{ color: 'var(--text)', fontSize: '1.1rem' }}>Loading...</p>
      </div>
    </div>
  );
}

const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <Suspense fallback={<Loading />}>
        <HomePage />
      </Suspense>
    ),
  },
  {
    path: '/demo',
    element: (
      <Suspense fallback={<Loading />}>
        <DemoPage />
      </Suspense>
    ),
  },
  {
    path: '/process/:projectId',
    element: (
      <Suspense fallback={<Loading />}>
        <ProcessView />
      </Suspense>
    ),
  },
  {
    path: '/simulation/:simulationId',
    element: (
      <Suspense fallback={<Loading />}>
        <SimulationView />
      </Suspense>
    ),
  },
  {
    path: '/simulation/:simulationId/start',
    element: (
      <Suspense fallback={<Loading />}>
        <SimulationRunView />
      </Suspense>
    ),
  },
  {
    path: '/report/:reportId',
    element: (
      <Suspense fallback={<Loading />}>
        <ReportView />
      </Suspense>
    ),
  },
  {
    path: '/interaction/:reportId',
    element: (
      <Suspense fallback={<Loading />}>
        <InteractionView />
      </Suspense>
    ),
  },
]);

export default function AppRouter() {
  return <RouterProvider router={router} />;
}
