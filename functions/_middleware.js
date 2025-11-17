// Cloudflare Pages Functions middleware
export async function onRequest(context) {
  const { request, env, next } = context;

  // Add CORS headers
  const response = await next();
  const newResponse = new Response(response.body, response);

  newResponse.headers.set('Access-Control-Allow-Origin', '*');
  newResponse.headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  newResponse.headers.set('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  return newResponse;
}
