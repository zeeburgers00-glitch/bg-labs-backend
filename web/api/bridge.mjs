// Vercel provides the OIDC token in request context; resolve it inside each
// request, not at module load time or from an untrusted request header.
import {getVercelOidcTokenSync} from '@vercel/oidc';
import {createBridge} from '../../api/bridge.mjs';
export default createBridge({getGatewayToken:getVercelOidcTokenSync});
