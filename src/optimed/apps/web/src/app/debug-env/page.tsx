'use client';

export default function DebugEnv() {
  return (
    <div style={{ padding: '20px', fontFamily: 'monospace' }}>
      <h1>Environment Variables Debug</h1>
      <div>
        <h2>NEXT_PUBLIC_API_BASE_URL:</h2>
        <pre>{process.env.NEXT_PUBLIC_API_BASE_URL || 'undefined'}</pre>
      </div>
      <div>
        <h2>NEXT_PUBLIC_DEFAULT_FHIR_SERVER:</h2>
        <pre>{process.env.NEXT_PUBLIC_DEFAULT_FHIR_SERVER || 'undefined'}</pre>
      </div>
      <div>
        <h2>NEXT_PUBLIC_INFO_MODE:</h2>
        <pre>{process.env.NEXT_PUBLIC_INFO_MODE || 'undefined'}</pre>
      </div>
      <div>
        <h2>All process.env keys starting with NEXT_PUBLIC:</h2>
        <pre>{JSON.stringify(
          Object.keys(process.env)
            .filter(key => key.startsWith('NEXT_PUBLIC'))
            .reduce((obj, key) => {
              obj[key] = process.env[key];
              return obj;
            }, {} as Record<string, any>),
          null,
          2
        )}</pre>
      </div>
    </div>
  );
}