<?php

declare(strict_types=1);

namespace App\Controller;

use App\Cloud\CloudApiClient;
use App\Cloud\CloudApiException;
use App\Topology\TopologyMode;
use App\Topology\TopologyProvider;
use Symfony\Bundle\FrameworkBundle\Controller\AbstractController;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\Routing\Attribute\Route;

final class TopologyController extends AbstractController
{
    public function __construct(
        private readonly TopologyProvider $topologyProvider,
        private readonly ?CloudApiClient $cloudApiClient = null,
    ) {}

    #[Route('/api/topology', name: 'api_topology', methods: ['GET'])]
    public function topology(): JsonResponse
    {
        return new JsonResponse($this->topologyProvider->getTopology()->toJson());
    }

    /**
     * Troubleshooting view of the last Cloud services collection: one entry per page request with
     * success/failure, error, HTTP status, request id, and whether another page was advertised.
     * Always 200 — when cloud mode is off it simply reports that nothing was collected.
     */
    #[Route('/api/topology/services-collection', name: 'api_topology_services_collection', methods: ['GET'])]
    public function servicesCollection(): JsonResponse
    {
        $topology = $this->topologyProvider->getTopology();
        if ($this->cloudApiClient === null || $topology->mode !== TopologyMode::Cloud) {
            return new JsonResponse([
                'mode' => $topology->mode->value,
                'organizationId' => $topology->organizationId,
                'complete' => true,
                'stoppedReason' => null,
                'totalServices' => 0,
                'pages' => [],
            ]);
        }

        return new JsonResponse($this->cloudApiClient->servicesCollectionReport($topology->organizationId)->toArray());
    }

    /**
     * User-initiated wake of an idle/stopped Cloud service.
     *
     * For `stopped` — PATCH /state {"command": "start"} on control plane.
     * For `idle`    — GET /ping on data-plane HTTPS endpoint (`start` does not work for idle per Cloud docs).
     */
    #[Route('/api/targets/{id}/wake', name: 'api_target_wake', methods: ['POST'])]
    public function wake(string $id): JsonResponse
    {
        $topology = $this->topologyProvider->getTopology();
        if ($topology->mode !== TopologyMode::Cloud) {
            return new JsonResponse(['status' => false, 'error' => 'Wake is only supported in cloud mode.'], 400);
        }

        $target = $topology->findTargetById($id);
        if ($target === null) {
            return new JsonResponse(['status' => false, 'error' => 'Target not found.'], 404);
        }

        if ($this->cloudApiClient === null) {
            return new JsonResponse(['status' => false, 'error' => 'Cloud API client not configured.'], 500);
        }

        try {
            $this->cloudApiClient->wakeService(
                serviceId: $target->id,
                currentState: $target->state->value,
                httpsHost: $target->hosts[0] ?? null,
                httpsPort: $target->port,
            );
            // Drop the services cache so the next topology fetch observes the new state,
            // without waiting for the 30s TTL.
            $this->cloudApiClient->invalidateServicesCache($topology->organizationId);
        } catch (CloudApiException $e) {
            return new JsonResponse(['status' => false, 'error' => $e->getMessage()], 502);
        }

        return new JsonResponse([
            'status' => 'ok',
            'target_id' => $target->id,
            'message' => sprintf('Wake signal sent to service "%s".', $target->name),
        ]);
    }
}
