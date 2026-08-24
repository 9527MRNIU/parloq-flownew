import { describe, expect, it } from 'vitest'
import { ProtocolArtifactBuilder, ProtocolArtifactError } from './protocol-artifacts.js'

describe('ProtocolArtifactBuilder', () => {
  it('rejects protocol sources outside the registered adapter contract', async () => {
    const builder = new ProtocolArtifactBuilder('/tmp/parloq-protocol-artifact-test')
    await expect(builder.build({
      definitionId: '8541455568736000',
      adapterKey: 'custom',
      packageName: 'untrusted-package',
      version: '1.0.0',
      contractVersion: 1,
    })).rejects.toMatchObject({ code: 'invalid_request' } satisfies Partial<ProtocolArtifactError>)
  })
})
