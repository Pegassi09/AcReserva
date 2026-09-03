# MongoDB — coleções do AC Reserva

Não há migração SQL. Na primeira conexão, a API cria automaticamente os índices necessários nas coleções abaixo.

- `users`: acesso, hash de senha, perfis, setores autorizados e vínculo com associado.
- `associates` e `requesters`: empresas associadas e seus solicitantes.
- `sectors`, `rooms`, `equipment` e `room_blocks`: cadastro de recursos e indisponibilidades.
- `reservations`: evento, datas em UTC, serviços e equipamentos requisitados.
- `reservation_locks`: bloqueios usados dentro da transação para impedir concorrência entre reservas da mesma sala, empresa ou equipamento.
- `audit_logs` e `settings`: rastreabilidade e controle da configuração inicial.

Os índices únicos protegem e-mail, CNPJ, nome de sala/equipamento e protocolo. Os índices compostos das reservas aceleram a checagem de cota, disponibilidade de salas e equipamentos.

O MongoDB Atlas deve estar configurado como replica set (o padrão do Atlas), pois reservas e a criação do administrador usam transações.
